from __future__ import annotations

from sqlalchemy import select

from sim.agents.memory import retrieve_memories, write_memory
from sim.agents.update_rules import clip, engagement_level
from sim.core.ids import new_id
from sim.db.models import CircleContact, Message
from sim.engine.context import RunContext
from sim.llm.gateway import execute_model_call


def run(ctx: RunContext, sweep: int) -> None:
    policy_id = ctx.policy.spec.get("id", "phone_ban_6_12")
    for ar in ctx.agents.values():
        if not ar.escalated_inputs:
            continue
        contacts = list(
            ctx.session.scalars(select(CircleContact).where(CircleContact.agent_id == ar.agent.id))
        )
        roster_keys = [c.contact_key for c in contacts] or ["household"]
        memories = retrieve_memories(
            ctx.session,
            run_id=ctx.run.id,
            agent_id=ar.agent.id,
            query=" ".join(i.content for i in ar.escalated_inputs),
            k=8 if ar.tier == "standard" else 15,
            anchors=list(ar.agent.anchors or []),
        )
        # Strip per-row UUIDs so cache keys stay stable across replay runs.
        stable_inputs = [
            {k: v for k, v in i.model_dump(mode="json").items() if k not in ("id", "meta")}
            for i in ar.escalated_inputs
        ]
        stable_memories = [
            {k: v for k, v in m.items() if k != "id"} for m in memories
        ]
        call = execute_model_call(
            ctx.session,
            run_kind=ctx.run.kind,
            master_seed=ctx.run.master_seed,
            sweep=sweep,
            role="system2",
            request={
                "inputs": stable_inputs,
                "policy_id": policy_id,
                "roster_keys": roster_keys,
                "memories": stable_memories,
            },
            call_key=f"s2-{ar.agent.id}-{sweep}",
            config=ctx.config,
        )
        out = call.response
        update = out.get("policy_stance_update") or {}
        if update:
            stance = ctx.policy_stance(ar.agent.id, update.get("policy_id", policy_id))
            stance.aware = True
            if stance.first_heard_sweep is None:
                stance.first_heard_sweep = sweep
                stance.first_heard_from = ar.escalated_inputs[0].source
            stance.stance = clip(stance.stance + float(update.get("stance_delta", 0)), -3, 3)
            stance.certainty = float(update.get("certainty", stance.certainty))
            stance.salience = float(update.get("salience", stance.salience))
            stance.perceived_policy = update.get("perceived_policy")
            stance.perceived_personal_impact = update.get("perceived_personal_impact")
            stance.perceived_risks = list(update.get("perceived_risks") or [])
            stance.perceived_benefits = list(update.get("perceived_benefits") or [])
            stance.stance_source = "deliberate"
            stance.engagement = engagement_level(  # type: ignore[assignment]
                stance, civic_baseline=ar.agent.civic_baseline
            )
            ctx.set_policy_stance(ar.agent.id, stance)

        write_memory(
            ctx.session,
            run_id=ctx.run.id,
            agent_id=ar.agent.id,
            sweep=sweep,
            type="experience",
            content=out.get("interpretation") or "Thought about the week.",
            importance=int(out.get("importance") or 6),
            valence=-0.2,
            policy_id=policy_id,
        )

        for action in out.get("actions") or []:
            atype = action.get("type")
            if atype in ("talk", "post"):
                ar.messages.append({**action, "source": "system2"})
                # Circle subagent for talk
                if atype == "talk":
                    circle_call = execute_model_call(
                        ctx.session,
                        run_kind=ctx.run.kind,
                        master_seed=ctx.run.master_seed,
                        sweep=sweep,
                        role="circle",
                        request={
                            "shared_content": action.get("content"),
                            "channel": action.get("channel", "in_person"),
                            "contacts": [
                                {"contact_key": action.get("to") or roster_keys[0]}
                            ],
                        },
                        call_key=f"circle-{ar.agent.id}-{sweep}-{action.get('to')}",
                        config=ctx.config,
                    )
                    ar.pending_intents.append(
                        {
                            "type": "talk",
                            "action": action,
                            "circle": circle_call.response,
                            "model_call_id": str(circle_call.id),
                        }
                    )
                else:
                    ar.pending_intents.append({"type": atype, "action": action})
            elif atype and atype != "ignore":
                ar.pending_intents.append({"type": atype, "action": action})

        # Persist outbound messages
        for msg in ar.messages:
            row = Message(
                id=new_id(),
                run_id=ctx.run.id,
                sweep=sweep,
                sender=f"agent:{ar.agent.id}",
                recipients={"circle": [msg.get("to") or "household"]},
                channel=msg.get("channel") or "in_person",
                content=msg.get("content") or "",
                intent=msg.get("intent") or "inform",
                topic_tags=["phone_ban"],
            )
            ctx.session.add(row)
        ar.messages = []
    ctx.session.flush()
