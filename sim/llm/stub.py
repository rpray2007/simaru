from __future__ import annotations

from typing import Any

from sim.core.seeding import rng_for


class StubLLM:
    """Deterministic stub for System 2 / circle / world master / institutions / reflection."""

    def __init__(self, *, master_seed: int, model: str = "stub-llm", model_digest: str = "stub-llm-v1"):
        self.master_seed = master_seed
        self.model = model
        self.model_digest = model_digest

    def complete(
        self,
        role: str,
        request: dict[str, Any],
        *,
        sweep: int,
        call_key: str,
    ) -> dict[str, Any]:
        rng = rng_for(self.master_seed, "llm", sweep, role, call_key)
        if role == "system2":
            return self._system2(request, rng)
        if role == "circle":
            return self._circle(request, rng)
        if role.startswith("world_master"):
            return self._world_master(request, rng)
        if role == "institution":
            return self._institution(request, rng)
        if role == "reflection":
            return self._reflection(request, rng)
        if role == "narrative":
            return self._narrative(request, rng)
        if role == "embed":
            text = str(request.get("text", ""))
            from sim.agents.memory import stub_embedding

            return {"embedding": stub_embedding(text)}
        return {"ok": True, "role": role}

    def _system2(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        inputs = request.get("inputs") or []
        policy_id = request.get("policy_id") or "phone_ban_6_12"
        stance_delta = int(rng.integers(-2, 1))  # slight negative bias for phone ban
        actions: list[dict[str, Any]] = []
        if rng.random() < 0.6:
            roster = request.get("roster_keys") or ["household"]
            actions.append(
                {
                    "type": "talk",
                    "to": roster[0],
                    "channel": "in_person",
                    "content": "Did you hear about the phone ban?",
                    "intent_text": "mention policy at home",
                    "intent": "inform",
                }
            )
        return {
            "interpretation": f"Noticed {len(inputs)} thing(s) this week about school rules.",
            "emotion": {"label": "annoyed", "intensity": float(rng.uniform(0.2, 0.8))},
            "importance": int(rng.integers(4, 9)),
            "policy_stance_update": {
                "policy_id": policy_id,
                "aware": True,
                "stance_delta": stance_delta,
                "certainty": float(rng.uniform(0.3, 0.8)),
                "salience": float(rng.uniform(0.3, 0.9)),
                "perceived_policy": "all-day phone ban at school",
                "perceived_personal_impact": "phones locked during the day",
                "perceived_risks": ["harder to reach kids"],
                "perceived_benefits": ["fewer distractions"],
            },
            "actions": actions,
            "reasoning": "Stub System 2 appraisal.",
        }

    def _circle(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        contacts = request.get("contacts") or [{"contact_key": "household"}]
        reactions = []
        pass_on = []
        for c in contacts[:3]:
            key = c.get("contact_key", "contact")
            reactions.append(
                {
                    "contact_key": key,
                    "reply": "Yeah, I heard about that.",
                    "stance_expressed": int(rng.integers(-2, 2)),
                }
            )
            if rng.random() < 0.4:
                pass_on.append(
                    {
                        "contact_key": key,
                        "passed_on_version": "They're banning phones at school all day.",
                    }
                )
        return {"reactions": reactions, "landed": float(rng.uniform(0.2, 0.9)), "pass_on": pass_on, "end": True}

    def _world_master(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        outcomes = []
        for r in request.get("requests") or []:
            outcomes.append(
                {
                    "action_id": r.get("action_id", "unknown"),
                    "status": "done" if rng.random() < 0.8 else "partial",
                    "detail": "Stub world resolution.",
                    "agent_experience": "Things mostly went as expected.",
                }
            )
        deltas = []
        for hook in request.get("judgment_hooks") or []:
            deltas.append(
                {
                    "entity": hook.get("entity", "school"),
                    "change": {"field": hook.get("output_field", "enforcement.strictness"), "to": float(rng.uniform(0.3, 0.9))},
                    "cause": [f"judgment:{hook.get('id', 'hook')}"],
                    "confidence": 0.7,
                }
            )
        return {
            "outcomes": outcomes,
            "deltas": deltas,
            "event_realization": request.get("event_text") or "A quiet week in town.",
        }

    def _institution(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        triggered = bool(request.get("triggered"))
        if not triggered or rng.random() < 0.5:
            return {"response": "none", "reasoning": "Below threshold."}
        return {
            "response": "statement",
            "headline": "School board notes parent concerns",
            "text": "The board is monitoring implementation of the phone policy.",
            "framing": "implementation update",
            "reasoning": "Stub institution response.",
        }

    def _reflection(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        return {
            "reflections": [
                {
                    "content": "This week made me think about school rules.",
                    "importance": int(rng.integers(6, 9)),
                }
            ],
            "slow_proposals": [],
            "self_narrative_line": "",
        }

    def _narrative(self, request: dict[str, Any], rng: Any) -> dict[str, Any]:
        demo = request.get("demographics") or {}
        name = demo.get("name", "Resident")
        age = demo.get("age", 35)
        occ = demo.get("occupation", "worker")
        return {
            "biography": f"{name} is {age}, works as a {occ} in Maplewood.",
            "formative_experiences": ["Grew up nearby", "Values practicality"],
            "voice": {
                "fluency": "plain",
                "tics": ["you know"],
                "answer_length": "short",
                "polish_ceiling": "coworker",
                "samples": ["Yeah, that makes sense.", "I'm not sure about that."],
            },
            "quirks": ["Checks phone often"],
            "contradictions": [],
            "anchors": [f"Age {age}", f"Works as {occ}", "Lives in Maplewood"],
            "roster_seeds": [
                {
                    "label": "Household",
                    "sphere": "household",
                    "description": "Immediate household",
                    "stance_tendency": "mixed",
                },
                {
                    "label": "Close friend",
                    "sphere": "close",
                    "description": "Longtime friend",
                    "stance_tendency": "agree",
                },
            ],
        }
