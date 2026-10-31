from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from sim.db.models import Job


def enqueue_jobs(session: Session, jobs: Sequence[dict[str, Any]]) -> list[int]:
    """Insert jobs and return their ids."""
    rows: list[Job] = []
    for job in jobs:
        row = Job(
            run_id=job["run_id"],
            sweep=job["sweep"],
            phase=job["phase"],
            role=job["role"],
            payload=job["payload"],
            cache_key=job["cache_key"],
            status="queued",
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return [int(r.id) for r in rows]


def claim_jobs(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    role: str | None = None,
) -> list[Job]:
    """Claim queued jobs with FOR UPDATE SKIP LOCKED."""
    reclaim_stale_locks(session)
    stmt = (
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    if role is not None:
        stmt = stmt.where(Job.role == role)
    jobs = list(session.scalars(stmt))
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "running"
        job.locked_by = worker_id
        job.locked_at = now
        job.attempts += 1
    session.flush()
    return jobs


def reclaim_stale_locks(session: Session, older_than_minutes: int = 10) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    result = session.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < cutoff)
        .values(status="queued", locked_by=None, locked_at=None)
    )
    return int(result.rowcount or 0)


def complete_job(session: Session, job_id: int, result_call_id: UUID) -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    job.status = "done"
    job.result_call_id = result_call_id
    job.locked_by = None
    job.locked_at = None
    session.flush()
    session.execute(text("SELECT pg_notify('job_done', :payload)"), {"payload": str(job_id)})


def fail_job(session: Session, job_id: int, error: str) -> None:
    job = session.get(Job, job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = error
    job.locked_by = None
    job.locked_at = None
    session.flush()
    session.execute(text("SELECT pg_notify('job_done', :payload)"), {"payload": str(job_id)})


def wait_for_jobs(
    session: Session,
    job_ids: Sequence[int],
    *,
    timeout_s: float = 300.0,
    poll_s: float = 0.05,
) -> list[Job]:
    """Barrier: wait until all job_ids are done or failed."""
    if not job_ids:
        return []
    deadline = time.monotonic() + timeout_s
    ids = list(job_ids)
    while time.monotonic() < deadline:
        rows = list(session.scalars(select(Job).where(Job.id.in_(ids))))
        session.expire_all()
        if rows and all(r.status in ("done", "failed") for r in rows):
            failed = [r for r in rows if r.status == "failed"]
            if failed:
                raise RuntimeError(
                    f"{len(failed)} job(s) failed: {failed[0].error or 'unknown'}"
                )
            return rows
        time.sleep(poll_s)
        session.rollback()  # release snapshot for fresh read
    raise TimeoutError(f"Timed out waiting for jobs {ids}")


def count_pending(session: Session, run_id: UUID, sweep: int, phase: int) -> int:
    rows = session.scalars(
        select(Job).where(
            Job.run_id == run_id,
            Job.sweep == sweep,
            Job.phase == phase,
            Job.status.in_(("queued", "running")),
        )
    )
    return len(list(rows))
