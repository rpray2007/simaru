from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sim.core.seeding import rng_for
from sim.llm.gateway import execute_model_call
from sim.world.deltas import commit_delta


def entity_capacity(entity_id: str, fields: dict[str, Any] | None = None) -> int:
    fields = fields or {}
    if "capacity" in fields:
        return int(fields["capacity"])
    if "employees_real" in fields:
        return max(1, int(fields["employees_real"]) // 50)
    # Default weekly capacity for open-ended asks against an entity
    return 3


def batch_by_entity(intents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for intent in intents:
        entity = intent.get("target_entity") or intent.get("entity") or "world"
        groups[entity].append(intent)
    return groups


def resolve_collisions(
    ctx: Any,
    sweep: int,
    open_ended: list[dict[str, Any]],
    *,
    entity_fields: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group open-ended intents by target entity; respect capacity; call world master per batch."""
    entity_fields = entity_fields or {}
    results: list[dict[str, Any]] = []
    groups = batch_by_entity(open_ended)

    for entity_id, batch in groups.items():
        # Seeded order
        order_rng = rng_for(ctx.run.master_seed, "order", sweep, entity_id)
        indexed = list(enumerate(batch))
        order_rng.shuffle(indexed)
        ordered = [b for _, b in indexed]
        cap = entity_capacity(entity_id, entity_fields.get(entity_id))

        request_payload = {
            "place_name": "Maplewood",
            "canon_excerpt": f"Entity {entity_id} capacity={cap}",
            "policy_rules": ctx.policy.spec.get("rules"),
            "outcome_parameters": ctx.policy.spec.get("outcome_parameters"),
            "requests": [
                {k: v for k, v in r.items() if not k.startswith("_")} for r in ordered
            ],
            "prompt_context": {
                "place_name": "Maplewood",
                "canon_excerpt": f"Entity {entity_id} capacity={cap}",
                "policy_rules": str(ctx.policy.spec.get("rules")),
                "outcome_parameters": str(ctx.policy.spec.get("outcome_parameters")),
                "requests": [
                    {k: v for k, v in r.items() if not k.startswith("_")} for r in ordered
                ],
            },
        }
        call = execute_model_call(
            ctx.session,
            run_kind=ctx.run.kind,
            master_seed=ctx.run.master_seed,
            sweep=sweep,
            role="world_master_resolve",
            request=request_payload,
            call_key=f"resolve-{sweep}-{entity_id}",
            config=ctx.config,
        )

        # Apply capacity clamp regardless of model (collision invariant)
        granted = 0
        model_outcomes = {o.get("action_id"): o for o in (call.response.get("outcomes") or [])}

        for r in ordered:
            aid = r["action_id"]
            mo = model_outcomes.get(aid) or {}
            status = mo.get("status", "done")
            if status in ("granted", "done", "partial"):
                if granted >= cap:
                    status = "refused"
                    detail = f"Capacity {cap} reached for {entity_id}"
                else:
                    granted += 1
                    detail = mo.get("detail") or "ok"
            else:
                detail = mo.get("detail") or status
            row = r["_row"]
            row.outcome = {"status": status, "detail": detail, "entity": entity_id}
            row.model_call_id = call.id
            row.resolver = "world_master"
            results.append({"action_id": aid, "status": status, "entity": entity_id})

            ar = r.get("_ar")
            if ar is not None:
                from sim.agents.memory import write_memory

                write_memory(
                    ctx.session,
                    run_id=ctx.run.id,
                    agent_id=ar.agent.id,
                    sweep=sweep,
                    type="action",
                    content=mo.get("agent_experience") or detail,
                    importance=5,
                    valence=0.0 if status != "refused" else -0.3,
                )

        for d in call.response.get("deltas") or []:
            cause = d.get("cause") or []
            if not cause:
                continue
            commit_delta(
                ctx.session,
                run_id=ctx.run.id,
                sweep=sweep,
                entity_id=d.get("entity") or entity_id,
                change=d.get("change") or {},
                cause=cause,
                proposed_by="world_master",
                confidence=d.get("confidence"),
                description_update=d.get("description_update"),
                model_call_id=call.id,
                entity_fields=entity_fields.get(d.get("entity") or entity_id),
            )

    return results
