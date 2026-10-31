from sqlalchemy import select

from sim.db.models import Exposure, Metric, System1Decision, WorldDelta
from sim.engine.sweep import replay_run, run_experiment
from tests.conftest import requires_postgres


def _metrics_map(session, run_id):
    rows = list(
        session.scalars(
            select(Metric).where(Metric.run_id == run_id).order_by(Metric.sweep, Metric.name)
        )
    )
    return [(r.sweep, r.name, round(r.value, 6)) for r in rows]


@requires_postgres
def test_engine_nine_steps_and_replay(db_session):
    ctx = run_experiment(
        db_session,
        master_seed=17,
        n_agents=12,
        horizon_sweeps=3,
        kind="run",
    )
    assert ctx.run.status == "completed"
    assert ctx.run.current_sweep == 2

    decisions = list(
        db_session.scalars(select(System1Decision).where(System1Decision.run_id == ctx.run.id))
    )
    assert len(decisions) > 0

    deltas = list(db_session.scalars(select(WorldDelta).where(WorldDelta.run_id == ctx.run.id)))
    assert all(d.cause for d in deltas)

    # Exposures created for next sweep should not be readable same sweep — deliver_sweep = s+1
    exposures = list(db_session.scalars(select(Exposure).where(Exposure.run_id == ctx.run.id)))
    for exp in exposures:
        assert exp.deliver_sweep == exp.sweep_created + 1

    original_metrics = _metrics_map(db_session, ctx.run.id)
    assert any(name == "awareness" for _, name, _ in original_metrics)

    # Population checks from M2
    assert ctx.population.checks is not None
    assert "persona_consistency" in ctx.population.checks

    replay_ctx = replay_run(db_session, ctx.run.id, horizon_sweeps=3)
    assert replay_ctx.run.status == "completed"
    assert replay_ctx.run.kind == "replay"
    replay_metrics = _metrics_map(db_session, replay_ctx.run.id)
    assert replay_metrics == original_metrics


@requires_postgres
def test_no_intra_sweep_exposure_leakage(db_session):
    ctx = run_experiment(
        db_session,
        master_seed=21,
        n_agents=10,
        horizon_sweeps=2,
    )
    exposures = list(db_session.scalars(select(Exposure).where(Exposure.run_id == ctx.run.id)))
    # Any exposure created in sweep 0 must deliver in sweep 1+
    for exp in exposures:
        assert exp.deliver_sweep > exp.sweep_created
