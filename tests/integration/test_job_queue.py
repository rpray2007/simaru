from sim.core.ids import new_id
from sim.db import cache as model_cache
from sim.db.queue import claim_jobs, complete_job, enqueue_jobs, wait_for_jobs
from tests.conftest import requires_postgres


@requires_postgres
def test_skip_locked_claim_and_complete(db_session):
    run_id = new_id()
    ids = enqueue_jobs(
        db_session,
        [
            {
                "run_id": run_id,
                "sweep": 0,
                "phase": 4,
                "role": "system1",
                "payload": {"request": {"state": "x"}, "options": {}},
                "cache_key": "abc123",
            }
        ],
    )
    db_session.commit()
    jobs = claim_jobs(db_session, worker_id="w1", limit=1)
    assert len(jobs) == 1
    assert jobs[0].status == "running"
    row = model_cache.put_cached(
        db_session,
        cache_key="abc123",
        role="system1",
        model="stub",
        model_digest="v1",
        request={"x": 1},
        response={"ok": True},
    )
    complete_job(db_session, jobs[0].id, row.id)
    db_session.commit()
    done = wait_for_jobs(db_session, ids, timeout_s=5)
    assert done[0].status == "done"
    assert done[0].result_call_id == row.id
