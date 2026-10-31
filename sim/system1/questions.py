from __future__ import annotations

from typing import Any

# Internal engine form (options lists) used by stubs + routing helpers.
NOTICE_ROUTE_V1_INTERNAL: dict[str, dict[str, Any]] = {
    "notices": {"type": "choice", "options": ["yes", "no"]},
    "valence": {
        "type": "choice",
        "options": ["very negative", "negative", "neutral", "positive", "very positive"],
    },
    "arousal": {"type": "choice", "options": ["low", "medium", "high"]},
    "route": {"type": "choice", "options": ["ignore", "habit", "escalate"]},
    "habit_action": {
        "type": "choice",
        "options": ["none", "grumble at home", "mention to a coworker", "pay and move on"],
    },
    "relevance": {"type": "choice", "options": ["not me", "someone close", "me directly"]},
}


def notice_route_v1_openjev() -> dict[str, dict[str, Any]]:
    """OpenJev /v1/systemone question map (§10.3 → official wire shape).

    Docs: https://openjev.sh/docs and openjev-server SERVE.md
    """
    return {
        "notices": {
            "type": "noul",
            "instructions": (
                "Does this person notice or register the input described in the state "
                "(as opposed to overlooking it)?"
            ),
            "criteria": {
                "true": "They notice it enough to react or remember it",
                "false": "They overlook it or it does not register",
            },
        },
        "valence": {
            "type": "choice",
            "instructions": "What is their immediate emotional valence toward this input?",
            "criteria": {
                "very negative": "Strongly negative gut reaction",
                "negative": "Mildly negative",
                "neutral": "Neither positive nor negative",
                "positive": "Mildly positive",
                "very positive": "Strongly positive",
            },
        },
        "arousal": {
            "type": "choice",
            "instructions": "How activated / aroused are they by this input?",
            "criteria": {
                "low": "Calm, low activation",
                "medium": "Some activation",
                "high": "Highly activated or alarmed",
            },
        },
        "route": {
            "type": "choice",
            "instructions": (
                "How should this person process the input this week? "
                "ignore = let it pass; habit = quick routine reaction; "
                "escalate = pause and deliberate carefully."
            ),
            "criteria": {
                "ignore": "Not worth attention this week",
                "habit": "Routine reaction without deep thought",
                "escalate": "Needs careful in-character deliberation",
            },
        },
        "habit_action": {
            "type": "choice",
            "instructions": (
                "If they react by habit (without deep deliberation), which template fits best?"
            ),
            "criteria": {
                "none": "No outward habit action",
                "grumble at home": "Complain briefly to household",
                "mention to a coworker": "Mention it at work/school casually",
                "pay and move on": "Comply mechanically and move on",
            },
        },
        "relevance": {
            "type": "choice",
            "instructions": "Who is this mainly about, from their point of view?",
            "criteria": {
                "not me": "Mostly about others / distant",
                "someone close": "About someone close to them",
                "me directly": "Affects them directly",
            },
        },
    }


def to_openjev_questions(questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Convert internal {type, options[]} specs into OpenJev criteria maps when needed."""
    out: dict[str, dict[str, Any]] = {}
    for name, spec in questions.items():
        if "instructions" in spec and ("criteria" in spec or spec.get("type") == "noul"):
            out[name] = {
                "type": spec.get("type", "choice"),
                "instructions": spec["instructions"],
                **({"criteria": spec["criteria"]} if "criteria" in spec else {}),
            }
            continue
        qtype = spec.get("type", "choice")
        options = list(spec.get("options") or [])
        if qtype == "choice" or options:
            # Binary yes/no → noul is closer to OpenJev training for notice questions
            if options == ["yes", "no"] and name in ("notices",):
                out[name] = {
                    "type": "noul",
                    "instructions": spec.get("instructions") or f"Is '{name}' true for this state?",
                }
            else:
                out[name] = {
                    "type": "choice",
                    "instructions": spec.get("instructions")
                    or f"Choose the best value for '{name}'.",
                    "criteria": {o: None for o in options},
                }
        else:
            out[name] = {
                "type": qtype,
                "instructions": spec.get("instructions") or f"Answer '{name}'.",
            }
    return out
