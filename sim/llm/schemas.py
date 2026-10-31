from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Emotion(BaseModel):
    label: str
    intensity: float = Field(ge=0, le=1)


class PolicyStanceUpdate(BaseModel):
    policy_id: str | None = None
    aware: bool = True
    stance_delta: int = Field(default=0, ge=-2, le=2)
    certainty: float = Field(default=0.5, ge=0, le=1)
    salience: float = Field(default=0.5, ge=0, le=1)
    perceived_policy: str | None = None
    perceived_personal_impact: str | None = None
    perceived_risks: list[str] = Field(default_factory=list)
    perceived_benefits: list[str] = Field(default_factory=list)


class System2Action(BaseModel):
    type: Literal[
        "ignore",
        "talk",
        "post",
        "seek_information",
        "adapt_behavior",
        "comply",
        "evade",
        "game",
        "complain_formally",
        "organize",
        "join_group",
        "leave_group",
        "change_civic_intent",
    ]
    to: str | None = None
    group: str | None = None
    institution: str | None = None
    channel: Literal["in_person", "call", "text", "group_post", "formal"] | None = None
    content: str | None = Field(default=None, max_length=400)
    intent_text: str | None = Field(default=None, max_length=200)
    intent: (
        Literal["inform", "vent", "ask", "persuade", "joke", "organize", "reply"] | None
    ) = None
    reply_to: str | None = None


class System2Output(BaseModel):
    interpretation: str = Field(max_length=300)
    emotion: Emotion
    importance: int = Field(ge=1, le=10)
    policy_stance_update: PolicyStanceUpdate | None = None
    actions: list[System2Action] = Field(default_factory=list, max_length=4)
    reasoning: str = Field(max_length=300)


class CircleReaction(BaseModel):
    contact_key: str
    reply: str = Field(max_length=300)
    stance_expressed: int = Field(default=0, ge=-3, le=3)


class CirclePassOn(BaseModel):
    contact_key: str
    passed_on_version: str = Field(max_length=300)


class CircleOutput(BaseModel):
    reactions: list[CircleReaction] = Field(default_factory=list)
    landed: float = Field(ge=0, le=1)
    pass_on: list[CirclePassOn] = Field(default_factory=list)
    end: bool = True


class WorldOutcome(BaseModel):
    action_id: str
    status: Literal["granted", "refused", "partial", "done", "no_effect"] = "done"
    detail: str = Field(default="", max_length=300)
    agent_experience: str = Field(default="", max_length=200)


class WorldDeltaOut(BaseModel):
    entity: str
    change: dict[str, Any]
    description_update: str | None = None
    cause: list[str] = Field(min_length=1)
    confidence: float | None = None


class WorldMasterOutput(BaseModel):
    outcomes: list[WorldOutcome] = Field(default_factory=list)
    deltas: list[WorldDeltaOut] = Field(default_factory=list)
    event_realization: str | None = None


class InstitutionOutput(BaseModel):
    response: Literal["none", "statement", "enforcement_change", "amendment", "story"]
    headline: str | None = Field(default=None, max_length=120)
    text: str | None = Field(default=None, max_length=800)
    framing: str | None = Field(default=None, max_length=120)
    amendment: dict[str, Any] | None = None
    enforcement_change: dict[str, Any] | None = None
    reasoning: str | None = Field(default=None, max_length=300)


class ReflectionItem(BaseModel):
    content: str = Field(max_length=200)
    importance: int = Field(ge=6, le=9)


class SlowProposal(BaseModel):
    attribute: str
    direction: Literal["up", "down"]
    evidence_refs: list[str] = Field(default_factory=list)


class ReflectionOutput(BaseModel):
    reflections: list[ReflectionItem] = Field(default_factory=list, max_length=3)
    slow_proposals: list[SlowProposal] = Field(default_factory=list)
    self_narrative_line: str | None = Field(default=None, max_length=160)


class NarrativeVoice(BaseModel):
    fluency: str = "plain"
    tics: list[str] = Field(default_factory=list)
    answer_length: str = "short"
    polish_ceiling: str = "coworker"
    samples: list[str] = Field(default_factory=list)


class RosterSeed(BaseModel):
    label: str
    sphere: str
    description: str = ""
    stance_tendency: str | None = None


class NarrativeOutput(BaseModel):
    biography: str
    formative_experiences: list[str] = Field(default_factory=list)
    voice: NarrativeVoice = Field(default_factory=NarrativeVoice)
    quirks: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    roster_seeds: list[RosterSeed] = Field(default_factory=list)


ROLE_SCHEMA: dict[str, type[BaseModel]] = {
    "system2": System2Output,
    "circle": CircleOutput,
    "world_master": WorldMasterOutput,
    "world_master_resolve": WorldMasterOutput,
    "world_master_judgment": WorldMasterOutput,
    "world_master_realize": WorldMasterOutput,
    "institution": InstitutionOutput,
    "reflection": ReflectionOutput,
    "narrative": NarrativeOutput,
}


def schema_for_role(role: str) -> dict[str, Any] | None:
    model = ROLE_SCHEMA.get(role)
    if model is None:
        return None
    return model.model_json_schema()


def parse_role_output(role: str, data: dict[str, Any]) -> BaseModel | dict[str, Any]:
    model = ROLE_SCHEMA.get(role)
    if model is None:
        return data
    return model.model_validate(data)
