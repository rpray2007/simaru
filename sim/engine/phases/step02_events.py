from __future__ import annotations

from sim.core.ids import new_id
from sim.core.seeding import rng_for
from sim.db.models import Event
from sim.engine.context import RunContext
from sim.engine.types import Input
from sim.llm.gateway import execute_model_call


def run(ctx: RunContext, sweep: int) -> None:
    chaos = float(ctx.config.get("engine", {}).get("chaos_level", 1.0))
    # Ambient development
    ambient_rng = rng_for(ctx.run.master_seed, "ambient", sweep, "place")
    if ambient_rng.random() < 0.8:
        call = execute_model_call(
            ctx.session,
            run_kind=ctx.run.kind,
            master_seed=ctx.run.master_seed,
            sweep=sweep,
            role="world_master_realize",
            request={"event_text": "A small local development this week."},
            call_key=f"ambient-{sweep}",
            config=ctx.config,
        )
        text = call.response.get("event_realization") or "Something minor happened in town."
        event = Event(
            id=new_id(),
            run_id=ctx.run.id,
            sweep=sweep,
            channel="ambient",
            target={"world": True},
            draw={"type": "ambient", "magnitude": 0.2},
            realized={"text": text},
            model_call_id=call.id,
        )
        ctx.session.add(event)

    # Sparse life events
    for ar in ctx.agents.values():
        rng = rng_for(ctx.run.master_seed, "life_events", sweep, str(ar.agent.id))
        if rng.random() < 0.02 * chaos:
            content = "A minor household hassle took time this week."
            event = Event(
                id=new_id(),
                run_id=ctx.run.id,
                sweep=sweep,
                channel="life_event",
                target={"agent_id": str(ar.agent.id)},
                draw={"type": "household_hassle", "magnitude": 0.3},
                realized={"text": content},
            )
            ctx.session.add(event)
            ar.inputs.append(
                Input(
                    id=new_id(),
                    kind="life_event",
                    source="life_event",
                    content=content,
                    impact_magnitude=0.3,
                    closeness=1.0,
                )
            )
            ar.fast["stress"] = min(1.0, float(ar.fast.get("stress", 0.2)) + 0.1)
    ctx.session.flush()
