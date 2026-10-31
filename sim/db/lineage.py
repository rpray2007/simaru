from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.db.models import Run


def lineage(session: Session, run_id: UUID) -> list[tuple[UUID, int]]:
    """Return [(run_id, max_sweep), ...] from leaf to root.

    For a branch forked at fork_sweep=f from parent P:
    - child owns sweeps > f
    - parent owns sweeps <= f
    """
    chain: list[tuple[UUID, int]] = []
    current_id: UUID | None = run_id
    child_fork: int | None = None
    while current_id is not None:
        run = session.get(Run, current_id)
        if run is None:
            break
        max_sweep = run.current_sweep if child_fork is None else child_fork
        chain.append((run.id, max_sweep))
        child_fork = run.fork_sweep
        current_id = run.parent_run_id
    return chain


def resolve_run_for_sweep(session: Session, run_id: UUID, sweep: int) -> UUID:
    for rid, max_sweep in lineage(session, run_id):
        run = session.get(Run, rid)
        if run is None:
            continue
        if run.parent_run_id is None or sweep > (run.fork_sweep or -1):
            if sweep <= max_sweep or rid == run_id:
                return rid
    return run_id


def get_run(session: Session, run_id: UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise KeyError(f"Run not found: {run_id}")
    return run


def list_runs(session: Session) -> list[Run]:
    return list(session.scalars(select(Run).order_by(Run.created_at.desc())))
