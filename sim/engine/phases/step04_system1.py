from __future__ import annotations

import hashlib

from sim.agents.memory import write_memory
from sim.agents.update_rules import apply_gut_update, engagement_level
from sim.core.ids import new_id
from sim.db.models import System1Decision
from sim.engine.context import RunContext
from sim.llm.gateway import execute_model_call
from sim.system1.client import Decision
from sim.system1.questions import NOTICE_ROUTE_V1_INTERNAL, notice_route_v1_openjev
from sim.system1.routing import route_decision


def _content_key(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _question_set_for_config(config: dict) -> dict:
    """Use System One (noul/choice/criteria) questions for hosted Jev / OpenJev."""
    from sim.core.config import load_models

    models = load_models()
    name = (config.get("models") or {}).get("system1", "stub-system1")
    kind = (models.get(name) or {}).get("kind", "")
    if kind == "system_one":
        return notice_route_v1_openjev()
    return NOTICE_ROUTE_V1_INTERNAL


def _state_string(ar, inp) -> str:  # type: ignore[no-untyped-def]
    demo = ar.agent.demographics
    traits = ar.agent.traits
    policy_id = inp.policy_id or "phone_ban_6_12"
    stance = ar.policy_stances.get(policy_id) or {}
    return (
        f"Agent: {demo.get('name')}, {demo.get('age')}, {demo.get('occupation')}, "
        f"{demo.get('neighborhood')}. Household: size {demo.get('household', {}).get('size')}.\n"
        f"Traits: openness {traits.get('openness', 0.5):.2f}, neuroticism {traits.get('neuroticism', 0.5):.2f}. "
        f"Stress: {ar.fast.get('stress', 0.2):.2f}. Mood: {ar.fast.get('mood', 0.0):.2f}. "
        f"Attention left: {ar.fast.get('attention', 6):.1f}.\n"
        f"Engagement on {policy_id}: {stance.get('engagement', 'unaware')}. "
        f"Stance: {stance.get('stance', 0)}.\n"
        f"Input ({inp.kind}, from {inp.source}, closeness {inp.closeness}, "
        f"seen before: {inp.repeat_count}):\n{inp.content}\n"
        f"Impact on them: {'high' if inp.impact_magnitude >= 0.6 else 'medium' if inp.impact_magnitude >= 0.3 else 'low'}."
    )


def run(ctx: RunContext, sweep: int) -> None:
    s1_cfg = ctx.config.get("system1", {})
    max_esc = int(s1_cfg.get("max_escalations_per_agent", 3))
    conf_threshold = float(s1_cfg.get("conf_threshold", 0.7))
    question_set = _question_set_for_config(ctx.config)

    for ar in ctx.agents.values():
        stress = float(ar.fast.get("stress", 0.2))
        budget = float(ar.agent.attention_baseline) * (1 - 0.5 * stress)
        ar.fast["attention"] = budget
        ar.escalated_inputs = []
        # Sort by closeness × impact
        ordered = sorted(
            ar.inputs,
            key=lambda i: i.closeness * max(i.impact_magnitude, 0.1),
            reverse=True,
        )
        esc_count = 0
        for inp in ordered:
            cost = 1
            if budget < cost:
                break
            state = _state_string(ar, inp)
            call = execute_model_call(
                ctx.session,
                run_kind=ctx.run.kind,
                master_seed=ctx.run.master_seed,
                sweep=sweep,
                role="system1",
                request={"state": state, "questions": question_set},
                call_key=f"s1-{ar.agent.id}-{sweep}-{inp.kind}-{_content_key(inp.content)}",
                config=ctx.config,
            )
            answers = {k: Decision.model_validate(v) for k, v in call.response.items()}
            route, escalated_by = route_decision(
                answers,
                input_data=inp.model_dump(),
                agent={"policy_stances": ar.policy_stances},
                conf_threshold=conf_threshold,
            )
            if route == "escalate":
                cost = 2
                if budget < cost or esc_count >= max_esc:
                    route = "habit"
                    escalated_by = None
                else:
                    esc_count += 1
                    ar.escalated_inputs.append(inp)
            budget -= cost
            ar.fast["attention"] = budget

            ctx.session.add(
                System1Decision(
                    id=new_id(),
                    run_id=ctx.run.id,
                    sweep=sweep,
                    agent_id=ar.agent.id,
                    input_ref={"kind": inp.kind, "id": str(inp.id)},
                    question_set="notice_route_v1",
                    answers={k: v.model_dump() for k, v in answers.items()},
                    route=route,
                    escalated_by=escalated_by,
                    model_call_id=call.id,
                )
            )

            valence_map = {
                "very negative": -1.0,
                "negative": -0.5,
                "neutral": 0.0,
                "positive": 0.5,
                "very positive": 1.0,
            }
            valence = valence_map.get(str(answers.get("valence").value if answers.get("valence") else "neutral"), 0.0)
            importance = 2 if route == "ignore" else 4 if route == "habit" else 6
            write_memory(
                ctx.session,
                run_id=ctx.run.id,
                agent_id=ar.agent.id,
                sweep=sweep,
                type="experience",
                content=inp.content,
                importance=importance,
                valence=valence,
                source=inp.source,
                policy_id=inp.policy_id,
            )

            if route == "habit" and inp.policy_id:
                stance = ctx.policy_stance(ar.agent.id, inp.policy_id)
                stance = apply_gut_update(stance, valence)
                if stance.first_heard_sweep is None:
                    stance.first_heard_sweep = sweep
                    stance.first_heard_from = inp.source
                stance.engagement = engagement_level(  # type: ignore[assignment]
                    stance, civic_baseline=ar.agent.civic_baseline
                )
                ctx.set_policy_stance(ar.agent.id, stance)
                habit = answers.get("habit_action")
                if habit and habit.value == "grumble at home":
                    ar.messages.append(
                        {
                            "channel": "in_person",
                            "to": "household",
                            "content": "Ugh, this phone ban thing…",
                            "intent": "vent",
                            "source": "habit",
                        }
                    )
            elif route == "ignore":
                pass
        # Clear processed inputs; escalated kept separately for System 2
        ar.inputs = []
    ctx.session.flush()
