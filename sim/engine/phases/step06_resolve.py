from __future__ import annotations

from sqlalchemy import select

from sim.core.ids import new_id
from sim.core.seeding import rng_for
from sim.db.constants import BASELINE_RUN_ID
from sim.db.models import Action, Exposure, Membership
from sim.engine.context import RunContext
from sim.world.resolver import resolve_collisions


def run(ctx: RunContext, sweep: int) -> None:
    open_ended: list[dict] = []
    for ar in ctx.agents.values():
        for idx, intent in enumerate(ar.pending_intents):
            action = intent.get("action") or {}
            atype = intent.get("type") or action.get("type") or "ignore"
            intent_text = action.get("intent_text") or action.get("content") or atype
            action_key = f"{ar.agent.id}:{atype}:{idx}:{intent_text}"
            target = (
                action.get("institution")
                or action.get("group")
                or action.get("entity")
                or ("school_maplewood_high" if atype in ("adapt_behavior", "comply", "evade", "game") else "world")
            )
            row = Action(
                id=new_id(),
                run_id=ctx.run.id,
                sweep=sweep,
                agent_id=ar.agent.id,
                source=action.get("source") or "system2",
                type=atype,
                intent_text=intent_text,
                params=action,
                validation={"ok": True},
                resolver="bus" if atype in ("talk", "post") else "world_master",
            )
            ctx.session.add(row)
            ctx.session.flush()

            if atype in ("talk", "post"):
                _spread(ctx, sweep, ar.agent.id, intent, action_key)
                row.outcome = {"status": "done", "detail": "message delivered to bus"}
            else:
                open_ended.append(
                    {
                        "action_id": action_key,
                        "agent_id": str(ar.agent.id),
                        "intent_text": intent_text,
                        "agent_summary": ar.agent.demographics.get("name"),
                        "target_entity": target,
                        "percentile": int(
                            rng_for(
                                ctx.run.master_seed, "resolver", sweep, action_key
                            ).integers(1, 100)
                        ),
                        "_row": row,
                        "_ar": ar,
                    }
                )
        ar.pending_intents = []

    if open_ended:
        resolve_collisions(
            ctx,
            sweep,
            open_ended,
            entity_fields={
                "school_maplewood_high": {"capacity": 3, "enrollment": 1100},
                "workplace_hospital": {"capacity": 3, "employees_real": 900},
                "world": {"capacity": 10},
            },
        )
    ctx.session.flush()


def _spread(ctx: RunContext, sweep: int, agent_id, intent: dict, action_key: str) -> None:
    circle = intent.get("circle") or {}
    pass_on = circle.get("pass_on") or []
    landed = float(circle.get("landed") or 0.3)
    base = float(ctx.config.get("circle", {}).get("pass_on_base", {}).get("close", 0.15))
    p = min(1.0, base * landed)
    memberships = list(
        ctx.session.scalars(
            select(Membership).where(
                Membership.agent_id == agent_id,
                Membership.run_id == BASELINE_RUN_ID,
            )
        )
    )
    if not memberships:
        return
    ctx_id = memberships[0].context_id
    peers = list(
        ctx.session.scalars(
            select(Membership).where(
                Membership.context_id == ctx_id,
                Membership.run_id == BASELINE_RUN_ID,
                Membership.agent_id != agent_id,
            )
        )
    )
    rng = rng_for(ctx.run.master_seed, "circle_spread", sweep, action_key)
    content = (
        (pass_on[0].get("passed_on_version") if pass_on else None)
        or (intent.get("action") or {}).get("content")
        or "Heard about the phone ban."
    )
    n = 0
    for peer in peers:
        if n >= 5:
            break
        if rng.random() < p:
            ctx.session.add(
                Exposure(
                    id=new_id(),
                    run_id=ctx.run.id,
                    sweep_created=sweep,
                    deliver_sweep=sweep + 1,
                    agent_id=peer.agent_id,
                    source_kind="circle_spread",
                    message_id=None,
                    context_id=ctx_id,
                    path=[{"agent": str(agent_id)}, {"context": str(ctx_id)}],
                    content=content,
                    distorted=False,
                    status="pending",
                    expires_sweep=sweep
                    + 1
                    + int(ctx.config.get("messages", {}).get("expiry_sweeps", 2)),
                )
            )
            n += 1
