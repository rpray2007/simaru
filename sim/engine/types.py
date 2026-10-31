from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Input(BaseModel):
    id: UUID
    kind: Literal[
        "direct_impact",
        "life_event",
        "exposure",
        "media",
        "institution_notice",
        "circle_reply",
        "world_update",
    ]
    source: str
    content: str
    impact_magnitude: float = 0.0
    policy_id: str | None = None
    closeness: float = 0.0
    repeat_count: int = 0
    intent: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
