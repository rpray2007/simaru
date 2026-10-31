from __future__ import annotations

import argparse
import logging
from uuid import UUID

from sim.core.logging import setup_logging
from sim.db.session import session_scope
from sim.engine.sweep import run, run_experiment

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Sim sweep engine")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--agents", type=int, default=20)
    parser.add_argument("--sweeps", type=int, default=4)
    args = parser.parse_args()

    with session_scope() as session:
        if args.run_id:
            ctx = run(UUID(args.run_id), session)
        else:
            ctx = run_experiment(
                session,
                master_seed=args.seed,
                n_agents=args.agents,
                horizon_sweeps=args.sweeps,
            )
        logger.info(
            "engine_finished status=%s sweep=%s",
            ctx.run.status,
            ctx.run.current_sweep,
        )


if __name__ == "__main__":
    main()
