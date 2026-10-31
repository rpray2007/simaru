from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from sim.llm.schemas import ROLE_SCHEMA, System2Action, System2Output

BANNED_PHRASES = (
    "it's not either-or",
    "multifaceted",
    "as an ai",
    "as a language model",
)

FALLBACKS = {
    "system2": "habit",
    "circle": "none",
    "world_master": "no_effect",
    "world_master_resolve": "no_effect",
    "world_master_judgment": "no_effect",
    "world_master_realize": "no_effect",
    "institution": "none",
    "reflection": "decay_only",
    "narrative": "regenerate",
}


def voice_ok(text: str, *, max_sentences: int = 4) -> tuple[bool, list[str]]:
    errors: list[str] = []
    lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            errors.append(f"banned_phrase:{phrase}")
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) > max_sentences * 2:
        errors.append("too_long")
    return (len(errors) == 0, errors)


def validate_system2_semantics(
    output: System2Output,
    *,
    roster_keys: list[str] | None = None,
    groups: list[str] | None = None,
    civic_baseline: float = 0.4,
    engagement: str = "mild",
) -> tuple[System2Output, list[str]]:
    """Drop invalid actions individually; return cleaned output + error notes."""
    roster = set(roster_keys or [])
    group_set = set(groups or [])
    errors: list[str] = []
    kept: list[System2Action] = []
    eng_order = ["unaware", "indifferent", "mild", "engaged", "mobilized"]
    eng_idx = eng_order.index(engagement) if engagement in eng_order else 2

    for action in output.actions:
        if action.type == "talk" and action.to and roster and action.to not in roster:
            errors.append(f"talk.to invalid:{action.to}")
            continue
        if action.type == "post" and action.group and group_set and action.group not in group_set:
            errors.append(f"post.group invalid:{action.group}")
            continue
        need = {
            "talk": 2,
            "post": 2,
            "complain_formally": 3,
            "organize": 4,
        }.get(action.type, 0)
        if eng_idx < need:
            errors.append(f"engagement_ladder:{action.type}")
            continue
        if action.type == "organize" and civic_baseline < 0.7:
            errors.append("civic_baseline_blocks_organize")
            continue
        if action.type == "complain_formally" and civic_baseline < 0.4:
            errors.append("civic_baseline_blocks_complain")
            continue
        if action.content:
            ok, voice_errs = voice_ok(action.content)
            if not ok:
                errors.extend(voice_errs)
                continue
        kept.append(action)

    cleaned = output.model_copy(update={"actions": kept})
    return cleaned, errors


def parse_and_validate(
    role: str,
    raw: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool, list[str]]:
    """Return (payload, valid, errors)."""
    ctx = context or {}
    model = ROLE_SCHEMA.get(role)
    if model is None:
        return raw, True, []
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        return raw, False, [e.get("msg", str(e)) for e in exc.errors()]

    errors: list[str] = []
    if role == "system2" and isinstance(parsed, System2Output):
        parsed, errors = validate_system2_semantics(
            parsed,
            roster_keys=ctx.get("roster_keys"),
            groups=ctx.get("groups"),
            civic_baseline=float(ctx.get("civic_baseline", 0.4)),
            engagement=str(ctx.get("engagement", "mild")),
        )
    if hasattr(parsed, "cause") is False and role.startswith("world_master"):
        for d in getattr(parsed, "deltas", []) or []:
            if not getattr(d, "cause", None):
                errors.append("delta_missing_cause")
    data = parsed.model_dump()
    return data, len(errors) == 0, errors


def apply_fallback(role: str, request: dict[str, Any]) -> dict[str, Any]:
    kind = FALLBACKS.get(role, "none")
    if role == "system2" or kind == "habit":
        return {
            "interpretation": "Kept it simple this week.",
            "emotion": {"label": "neutral", "intensity": 0.2},
            "importance": 3,
            "policy_stance_update": None,
            "actions": [{"type": "ignore"}],
            "reasoning": "fallback_habit",
            "_fallback": True,
        }
    if role == "circle":
        return {"reactions": [], "landed": 0.0, "pass_on": [], "end": True, "_fallback": True}
    if role.startswith("world_master"):
        outcomes = []
        for r in request.get("requests") or []:
            outcomes.append(
                {
                    "action_id": r.get("action_id", "unknown"),
                    "status": "no_effect",
                    "detail": "fallback",
                    "agent_experience": "Nothing came of it.",
                }
            )
        return {"outcomes": outcomes, "deltas": [], "_fallback": True}
    if role == "institution":
        return {"response": "none", "reasoning": "fallback", "_fallback": True}
    if role == "reflection":
        return {"reflections": [], "slow_proposals": [], "_fallback": True}
    return {"_fallback": True, "ok": False}
