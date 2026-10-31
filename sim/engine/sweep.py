from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from sim.engine.context import RunContext, create_run
from sim.engine.phases import PHASES

logger = logging.getLogger(__name__)


def sweep(ctx: RunContext, s: int) -> None:
    for i, phase in enumerate(PHASES, start=1):
        logger.info("phase_start", extra={"run_id": str(ctx.run.id), "sweep": s, "phase": i})
        phase(ctx, s)


def run(run_id: UUID, session: Session) -> RunContext:
    ctx = RunContext.load(session, run_id)
    ctx.set_status("running")
    session.commit()
    for s in range(ctx.start_sweep, ctx.horizon):
        if ctx.pause_requested():
            ctx.set_status("paused")
            session.commit()
            return ctx
        # Fresh working buffers each sweep (inputs accumulate in phases)
        for ar in ctx.agents.values():
            ar.inputs = []
            ar.pending_intents = []
            ar.messages = []
        sweep(ctx, s)
        ctx.commit_sweep(s)
        session.commit()
        logger.info("sweep_done", extra={"run_id": str(ctx.run.id), "sweep": s})
    ctx.set_status("completed")
    session.commit()
    return ctx


def run_experiment(
    session: Session,
    *,
    master_seed: int = 17,
    n_agents: int = 20,
    horizon_sweeps: int = 4,
    kind: str = "run",
    experiment: str = "maplewood-phone-ban",
    config_overrides: dict[str, Any] | None = None,
) -> RunContext:
    run_row = create_run(
        session,
        experiment=experiment,
        master_seed=master_seed,
        n_agents=n_agents,
        horizon_sweeps=horizon_sweeps,
        kind=kind,
        config_overrides=config_overrides,
    )
    session.commit()
    return run(run_row.id, session)


def replay_run(session: Session, source_run_id: UUID, *, horizon_sweeps: int | None = None) -> RunContext:
    """Create a replay run that must be served entirely from cache."""
    from sim.core.config import config_hash
    from sim.core.ids import new_id
    from sim.db.models import Run

    source = session.get(Run, source_run_id)
    if source is None:
        raise KeyError(source_run_id)
    cfg = dict(source.config)
    if horizon_sweeps is not None:
        cfg.setdefault("engine", {})
        cfg["engine"] = {**cfg.get("engine", {}), "horizon_sweeps": horizon_sweeps}
    replay = Run(
        id=new_id(),
        experiment=source.experiment,
        population_id=source.population_id,
        policy_package_id=source.policy_package_id,
        master_seed=source.master_seed,
        config=cfg,
        config_hash=config_hash(cfg),
        model_manifest=source.model_manifest,
        parent_run_id=None,
        status="queued",
        current_sweep=-1,
        kind="replay",
    )
    session.add(replay)
    session.commit()
    return run(replay.id, session)
