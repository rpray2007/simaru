from __future__ import annotations

from sqlalchemy import select

from sim.core.ids import new_id
from sim.db.constants import BASELINE_RUN_ID
from sim.db.models import WorldEntity
from sim.engine.context import RunContext
from sim.llm.gateway import execute_model_call
from sim.world.deltas import commit_delta
from sim.world.rules import run_mechanic


def run(ctx: RunContext, sweep: int) -> None:
    spec = ctx.policy.spec
    policy_id = spec.get("id", "phone_ban_6_12")
    effective = int(spec.get("effective_sweep", 1))

    # Apply policy field changes at effective sweep.
    if sweep == effective:
        for rule in spec.get("rules") or []:
            applies = rule.get("applies_to") or {}
            if applies.get("entity_kind") == "school":
                schools = list(
                    ctx.session.scalars(
                        select(WorldEntity).where(
                            WorldEntity.place_id == ctx.population.place_id,
                            WorldEntity.kind == "school",
                            WorldEntity.run_id == BASELINE_RUN_ID,
                            WorldEntity.sweep == -1,
                        )
                    )
                )
                for school in schools:
                    fields = dict(school.fields)
                    effect = rule.get("effect") or {}
                    path = effect.get("set_field", "rules.phones")
                    parts = path.split(".")
                    cursor = fields
                    for p in parts[:-1]:
                        cursor = cursor.setdefault(p, {})
                    cursor[parts[-1]] = effect.get("value")
                    ctx.session.add(
                        WorldEntity(
                            place_id=school.place_id,
                            entity_id=school.entity_id,
                            run_id=ctx.run.id,
                            sweep=sweep,
                            kind=school.kind,
                            name=school.name,
                            fields=fields,
                            description=school.description,
                            invented=school.invented,
                            sources=school.sources,
                        )
                    )
                    commit_delta(
                        ctx.session,
                        run_id=ctx.run.id,
                        sweep=sweep,
                        entity_id=school.entity_id,
                        change={"field": path, "from": "allowed", "to": effect.get("value")},
                        cause=[f"policy:{policy_id}"],
                        proposed_by="rules_engine",
                    )

    # Announcement as world_update inputs at announce_sweep.
    if sweep == int(spec.get("announce_sweep", 0)):
        for ann in spec.get("announcements") or []:
            if int(ann.get("sweep", 0)) != sweep:
                continue
            from sim.engine.types import Input

            for ar in ctx.agents.values():
                ar.inputs.append(
                    Input(
                        id=new_id(),
                        kind="institution_notice",
                        source="institution:maplewood_usd",
                        content=ann["text"],
                        impact_magnitude=0.35,
                        policy_id=policy_id,
                        closeness=0.2,
                        repeat_count=0,
                    )
                )

    # Mechanical impacts.
    for mech in spec.get("mechanics") or []:
        name = mech.get("per_agent")
        if not name:
            continue
        for ar in ctx.agents.values():
            agent_view = {
                "demographics": ar.agent.demographics,
                "policy_stances": ar.policy_stances,
            }
            inputs = run_mechanic(
                name,
                agent=agent_view,
                sweep=sweep,
                policy_id=policy_id,
                effective_sweep=effective,
            )
            ar.inputs.extend(inputs)

    # Judgment hooks via world master (stub/cached).
    hooks = spec.get("judgment_hooks") or []
    if hooks:
        call = execute_model_call(
            ctx.session,
            run_kind=ctx.run.kind,
            master_seed=ctx.run.master_seed,
            sweep=sweep,
            role="world_master_judgment",
            request={"judgment_hooks": [{"id": h["id"], "entity": "school_maplewood_high", "output_field": h.get("output_field")} for h in hooks]},
            call_key=f"judgment-{sweep}",
            config=ctx.config,
        )
        for d in call.response.get("deltas") or []:
            cause = d.get("cause") or ["judgment"]
            if not cause:
                continue
            commit_delta(
                ctx.session,
                run_id=ctx.run.id,
                sweep=sweep,
                entity_id=d.get("entity", "school_maplewood_high"),
                change=d.get("change") or {},
                cause=cause,
                proposed_by="world_master",
                confidence=d.get("confidence"),
                model_call_id=call.id,
            )
    ctx.session.flush()
