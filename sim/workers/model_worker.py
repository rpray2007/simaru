from __future__ import annotations

import argparse
import logging
import time
import uuid

from sim.core.config import load_models, merge_config
from sim.core.logging import setup_logging
from sim.db import cache as model_cache
from sim.db.queue import claim_jobs, complete_job, fail_job
from sim.db.session import session_scope
from sim.llm.gateway import _execute_kind

logger = logging.getLogger(__name__)


def process_once(worker_id: str, *, limit: int = 4) -> int:
    with session_scope() as session:
        jobs = claim_jobs(session, worker_id=worker_id, limit=limit)
        if not jobs:
            return 0
        models = load_models()
        config = merge_config()
        for job in jobs:
            try:
                hit = model_cache.get_cached(session, job.cache_key)
                if hit is not None:
                    complete_job(session, job.id, hit.id)
                    continue
                payload = job.payload or {}
                request = payload.get("request") or {}
                options = payload.get("options") or {}
                model_name = payload.get("model_name") or "stub-llm"
                entry = models.get(
                    model_name,
                    {"kind": "stub_llm", "model": model_name, "model_digest": "unknown", "name": model_name},
                )
                entry = {"name": model_name, **entry}
                call_key = payload.get("call_key") or str(job.id)
                response, latency_ms, attempts, valid = _execute_kind(
                    kind=entry.get("kind", "stub_llm"),
                    role=job.role,
                    request=request,
                    master_seed=int(options.get("seed", 0)),
                    sweep=job.sweep,
                    call_key=call_key,
                    entry=entry,
                    options=options,
                    config=config,
                )
                row = model_cache.put_cached(
                    session,
                    cache_key=job.cache_key,
                    role=job.role,
                    model=entry.get("model", model_name),
                    model_digest=entry.get("model_digest", "unknown"),
                    request={"request": request, "options": options},
                    response=response,
                    latency_ms=latency_ms,
                    attempts=attempts,
                    valid=valid,
                )
                complete_job(session, job.id, row.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("job_failed")
                fail_job(session, job.id, str(exc))
        return len(jobs)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Sim model worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll", type=float, default=0.5)
    args = parser.parse_args()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    if args.once:
        process_once(worker_id)
        return
    while True:
        n = process_once(worker_id)
        if n == 0:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
