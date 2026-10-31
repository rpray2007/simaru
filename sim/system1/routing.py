from __future__ import annotations

from typing import Any

from sim.system1.client import Decision


def route_decision(
    answers: dict[str, Decision],
    *,
    input_data: dict[str, Any],
    agent: dict[str, Any],
    conf_threshold: float = 0.7,
) -> tuple[str, str | None]:
    """Apply notice_route_v1 routing rules. Returns (route, escalated_by)."""
    notices = answers.get("notices")
    route_ans = answers.get("route")
    arousal = answers.get("arousal")

    if notices and notices.value == "no" and notices.confidence >= 0.7:
        return "ignore", None

    impact = float(input_data.get("impact_magnitude", 0.0))
    closeness = float(input_data.get("closeness", 0.0))
    repeat_count = int(input_data.get("repeat_count", 0))
    intent = input_data.get("intent")

    if arousal and arousal.value == "high":
        return "escalate", "trigger:arousal"
    if impact >= 0.6:
        return "escalate", "trigger:impact"
    if closeness >= 0.7 and intent == "ask":
        return "escalate", "trigger:close_ask"
    if repeat_count >= 2:
        return "escalate", "trigger:repeat"

    stances = agent.get("policy_stances") or {}
    valence = answers.get("valence")
    if valence and stances:
        for st in stances.values():
            stance_val = float(st.get("stance", 0))
            if abs(stance_val) >= 2:
                neg = valence.value in ("negative", "very negative")
                pos = valence.value in ("positive", "very positive")
                if (stance_val > 0 and neg) or (stance_val < 0 and pos):
                    return "escalate", "trigger:belief_clash"

    if route_ans and route_ans.value == "escalate":
        return "escalate", "route"
    if route_ans and route_ans.confidence < conf_threshold:
        return "escalate", "low_confidence"
    if route_ans:
        return str(route_ans.value), None
    return "ignore", None
