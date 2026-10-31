from __future__ import annotations

from sim.agents.memory import write_memory
from sim.agents.update_rules import apply_decay
from sim.engine.context import RunContext
from sim.llm.gateway import execute_model_call


def run(ctx: RunContext, sweep: int) -> None:
    cycle = int(ctx.config.get("reflection", {}).get("cycle_sweeps", 4))
    decay_cfg = ctx.config.get("decay", {})

    for idx, ar in enumerate(ctx.agents.values()):
        # Deterministic agent index from enumeration order (stable per run load order)
        scheduled = (idx % cycle) == (sweep % cycle)
        escalated = bool(ar.escalated_inputs)
        if escalated or scheduled:
            call = execute_model_call(
                ctx.session,
                run_kind=ctx.run.kind,
                master_seed=ctx.run.master_seed,
                sweep=sweep,
                role="reflection",
                request={"agent_id": str(ar.agent.id), "tier": ar.tier},
                call_key=f"reflect-{ar.agent.id}-{sweep}",
                config=ctx.config,
            )
            for ref in call.response.get("reflections") or []:
                write_memory(
                    ctx.session,
                    run_id=ctx.run.id,
                    agent_id=ar.agent.id,
                    sweep=sweep,
                    type="reflection",
                    content=ref.get("content") or "",
                    importance=int(ref.get("importance") or 6),
                    valence=0.0,
                )
        ar.fast = apply_decay(
            ar.fast,
            mood_blend=float(decay_cfg.get("mood_to_baseline", 0.5)),
            concern_factor=float(decay_cfg.get("concern_salience", 0.6)),
        )
        # Reset attention baseline for next sweep
        ar.fast["attention"] = float(ar.agent.attention_baseline)
        ar.escalated_inputs = []
    ctx.session.flush()
