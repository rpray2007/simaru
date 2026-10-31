from __future__ import annotations

from typing import Any

from sim.agents.profile import Fast, PolicyStance


def clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def apply_gut_update(stance: PolicyStance, valence: float, *, step_max: float = 0.5) -> PolicyStance:
    updated = stance.model_copy(deep=True)
    updated.stance = clip(updated.stance + clip(valence * 0.5, -step_max, step_max), -3, 3)
    updated.certainty = min(updated.certainty, 0.3)
    updated.stance_source = "gut"
    if not updated.aware:
        updated.aware = True
    return updated


def engagement_level(
    stance: PolicyStance,
    *,
    civic_baseline: float,
    actions_taken: int = 0,
) -> str:
    if not stance.aware:
        return "unaware"
    magnitude = abs(stance.stance)
    if magnitude < 0.6 or stance.salience < 0.2:
        level = "indifferent"
    elif magnitude < 1.6:
        level = "mild"
    elif magnitude < 2.4:
        level = "engaged"
    else:
        level = "mobilized"
    if actions_taken > 0 and level == "indifferent":
        level = "mild"
    order = ["unaware", "indifferent", "mild", "engaged", "mobilized"]
    if level == "mobilized" and civic_baseline < 0.7:
        level = "engaged"
    if level == "engaged" and civic_baseline < 0.4:
        level = "mild"
    # Clamp to at most one level move from current.
    cur = order.index(stance.engagement) if stance.engagement in order else 0
    nxt = order.index(level)
    if nxt > cur + 1:
        level = order[cur + 1]
    elif nxt < cur - 1:
        level = order[cur - 1]
    return level


def apply_decay(fast: Fast | dict[str, Any], *, mood_blend: float = 0.5, concern_factor: float = 0.6) -> dict[str, Any]:
    state = Fast.model_validate(fast)
    state.mood = state.mood * (1 - mood_blend)
    kept = []
    for c in state.concerns:
        c.salience *= concern_factor
        if c.salience >= 0.05:
            kept.append(c)
    state.concerns = kept
    return state.model_dump()
