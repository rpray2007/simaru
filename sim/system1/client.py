from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from sim.core.seeding import derive_seed, rng_for


class Decision(BaseModel):
    value: Any
    probs: dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0


class System1Client(Protocol):
    def decide(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Decision]: ...


class StubSystem1Client:
    """Deterministic System 1 stub for M1–M3 (no OpenJev)."""

    def __init__(self, *, master_seed: int = 0, sweep: int = 0, agent_key: str = "agent"):
        self.master_seed = master_seed
        self.sweep = sweep
        self.agent_key = agent_key

    def decide(self, state: str, questions: dict[str, dict[str, Any]]) -> dict[str, Decision]:
        rng = rng_for(self.master_seed, "system1", self.sweep, self.agent_key, state[:80])
        out: dict[str, Decision] = {}
        impact_high = "Impact on them: high" in state or "me directly" in state.lower()
        policyish = "phone" in state.lower() or "ban" in state.lower() or "policy" in state.lower()
        for name, spec in questions.items():
            options = list(spec.get("options", ["yes", "no"]))
            if name == "notices":
                value = "yes" if policyish or impact_high or rng.random() < 0.7 else "no"
            elif name == "valence":
                value = "negative" if policyish else options[int(rng.integers(0, len(options)))]
            elif name == "arousal":
                value = "high" if impact_high else ("medium" if policyish else "low")
            elif name == "route":
                if impact_high or (policyish and rng.random() < 0.55):
                    value = "escalate"
                elif policyish:
                    value = "habit"
                else:
                    value = "ignore"
            elif name == "habit_action":
                value = options[1] if len(options) > 1 and policyish else options[0]
            elif name == "relevance":
                value = "me directly" if impact_high else ("someone close" if policyish else "not me")
            else:
                value = options[int(rng.integers(0, len(options)))]
            probs = {o: (0.7 if o == value else 0.3 / max(1, len(options) - 1)) for o in options}
            out[name] = Decision(value=value, probs=probs, confidence=0.85)
        # Touch seed channel for determinism audit.
        _ = derive_seed(self.master_seed, "system1", self.sweep, self.agent_key)
        return out
