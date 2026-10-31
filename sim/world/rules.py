from __future__ import annotations

from typing import Any
from uuid import UUID

from sim.core.ids import new_id
from sim.engine.types import Input


def phone_ban_daily_impact(
    *,
    agent: dict[str, Any],
    sweep: int,
    policy_id: str,
    effective_sweep: int,
) -> list[Input]:
    """Mechanical per-agent effects of the phone ban once effective."""
    if sweep < effective_sweep:
        return []
    demo = agent.get("demographics") or {}
    age = int(demo.get("age", 30))
    has_child = bool((demo.get("household") or {}).get("has_school_child"))
    is_student = age < 18
    if not (is_student or has_child):
        return []
    who = "you" if is_student else "your child"
    return [
        Input(
            id=new_id(),
            kind="direct_impact",
            source="policy:phone_ban_6_12",
            content=(
                f"This week {who} had to put a phone in a locked pouch at school all day."
            ),
            impact_magnitude=0.65 if is_student else 0.45,
            policy_id=policy_id,
            closeness=1.0,
            repeat_count=max(0, sweep - effective_sweep),
        )
    ]


MECHANICS = {
    "phone_ban.daily_impact": phone_ban_daily_impact,
}


def run_mechanic(name: str, **kwargs: Any) -> list[Input]:
    fn = MECHANICS.get(name)
    if fn is None:
        return []
    return fn(**kwargs)
