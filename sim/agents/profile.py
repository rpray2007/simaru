from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    attribute: str
    direction: Literal["up", "down"]
    source: str
    trusted: bool = False
    sweep: int


class Concern(BaseModel):
    topic: str
    salience: float = 0.0


class Slow(BaseModel):
    attitudes: dict[str, float] = Field(default_factory=dict)
    trust: dict[str, float] = Field(default_factory=dict)
    identity_strength: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    worries: list[str] = Field(default_factory=list)
    self_narrative_additions: list[list[Any]] = Field(default_factory=list)
    pending_evidence: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class Fast(BaseModel):
    circumstances: dict[str, Any] = Field(default_factory=dict)
    mood: float = 0.0
    stress: float = 0.2
    concerns: list[Concern] = Field(default_factory=list)
    attention: float = 6.0
    civic_intent: dict[str, Any] = Field(default_factory=dict)
    footprint_overrides: dict[str, Any] = Field(default_factory=dict)


class PolicyStance(BaseModel):
    policy_id: str
    aware: bool = False
    first_heard_sweep: int | None = None
    first_heard_from: str | None = None
    perceived_policy: str | None = None
    perceived_personal_impact: str | None = None
    perceived_risks: list[str] = Field(default_factory=list)
    perceived_benefits: list[str] = Field(default_factory=list)
    stance: float = 0.0
    certainty: float = 0.0
    salience: float = 0.0
    engagement: Literal["unaware", "indifferent", "mild", "engaged", "mobilized"] = "unaware"
    stance_source: Literal["gut", "deliberate"] = "gut"


def default_slow() -> dict[str, Any]:
    return Slow().model_dump()


def default_fast(*, attention: float = 6.0, stress: float = 0.2) -> dict[str, Any]:
    return Fast(attention=attention, stress=stress).model_dump()
