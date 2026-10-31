from __future__ import annotations

from sqlalchemy import select

from sim.core.ids import new_id
from sim.db.models import Exposure
from sim.engine.context import RunContext
from sim.engine.types import Input


def run(ctx: RunContext, sweep: int) -> None:
    # Expire old exposures
    for exp in ctx.session.scalars(
        select(Exposure).where(
            Exposure.run_id == ctx.run.id,
            Exposure.status == "pending",
            Exposure.expires_sweep < sweep,
        )
    ):
        exp.status = "expired"

    due = list(
        ctx.session.scalars(
            select(Exposure).where(
                Exposure.run_id == ctx.run.id,
                Exposure.deliver_sweep == sweep,
                Exposure.status == "pending",
            )
        )
    )
    for exp in due:
        ar = ctx.agents.get(exp.agent_id)
        if ar is None:
            continue
        ar.inputs.append(
            Input(
                id=new_id(),
                kind="exposure",
                source=exp.source_kind,
                content=exp.content,
                impact_magnitude=0.3,
                policy_id=ctx.policy.spec.get("id"),
                closeness=0.3,
                repeat_count=0,
                meta={"exposure_id": str(exp.id), "path": exp.path},
            )
        )
        exp.status = "read"
    ctx.session.flush()
