from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Place(Base):
    __tablename__ = "places"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    boundary_geojson: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    jurisdictions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    import_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="approved")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("slug", "version", name="uq_places_slug_version"),)


class WorldEntity(Base):
    __tablename__ = "world_entities"

    place_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("places.id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Use BASELINE_RUN_ID for pack baseline (Postgres PK columns cannot be NULL).
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    sweep: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    geom_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    invented: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class WorldDelta(Base):
    __tablename__ = "world_deltas"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    change: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description_update: Mapped[str | None] = mapped_column(Text)
    cause: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    proposed_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")
    check_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model_call_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Population(Base):
    __tablename__ = "populations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    place_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("places.id"), nullable=False)
    sampling_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    generator_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checks: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="building")
    baseline_sweep: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    population_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("populations.id"), nullable=False, index=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, default="standard")
    is_synthetic_tail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demographics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    traits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    voice: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anchors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    footprint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    home_lon: Mapped[float | None] = mapped_column(Float)
    home_lat: Mapped[float | None] = mapped_column(Float)
    donors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    civic_baseline: Mapped[float] = mapped_column(Float, nullable=False, default=0.4)
    attention_baseline: Mapped[float] = mapped_column(Float, nullable=False, default=6.0)


class AgentState(Base):
    __tablename__ = "agent_state"

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    sweep: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    slow: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    fast: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    policy_stances: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Context(Base):
    __tablename__ = "contexts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    place_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("places.id"), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)  # BASELINE_RUN_ID for pack
    created_sweep: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    real_size: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Membership(Base):
    __tablename__ = "memberships"

    context_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    from_sweep: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)  # BASELINE_RUN_ID for pack
    role: Mapped[str | None] = mapped_column(Text)
    to_sweep: Mapped[int | None] = mapped_column(Integer)


class CircleContact(Base):
    __tablename__ = "circle_contacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    sphere: Mapped[str] = mapped_column(Text, nullable=False)
    context_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    match_filter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    stance_tendency: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aggregate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("agent_id", "contact_key", name="uq_circle_agent_key"),)


class CircleState(Base):
    __tablename__ = "circle_state"

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    sweep: Mapped[int] = mapped_column(Integer, primary_key=True)
    closeness: Mapped[float] = mapped_column(Float, nullable=False)
    contact_memory: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    sender: Mapped[str] = mapped_column(Text, nullable=False)
    recipients: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    stance_expressed: Mapped[int | None] = mapped_column(SmallInteger)
    emotion: Mapped[str | None] = mapped_column(Text)
    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    reply_to: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lineage: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    engagement: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Exposure(Base):
    __tablename__ = "exposures"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep_created: Mapped[int] = mapped_column(Integer, nullable=False)
    deliver_sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    context_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    path: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    distorted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    expires_sweep: Mapped[int] = mapped_column(Integer, nullable=False)


class PolicyPackage(Base):
    __tablename__ = "policy_packages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    place_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("places.id"), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (UniqueConstraint("slug", "version", name="uq_policy_slug_version"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    experiment: Mapped[str] = mapped_column(Text, nullable=False)
    population_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("populations.id"), nullable=False
    )
    policy_package_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("policy_packages.id"), nullable=False
    )
    master_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parent_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("runs.id"))
    fork_sweep: Mapped[int | None] = mapped_column(Integer)
    intervention: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    current_sweep: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="run")
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class System1Decision(Base):
    __tablename__ = "system1_decisions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    input_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    question_set: Mapped[str] = mapped_column(Text, nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    route: Mapped[str] = mapped_column(Text, nullable=False)
    escalated_by: Mapped[str | None] = mapped_column(Text)
    model_call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    intent_text: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    resolver: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    delta_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list)
    model_call_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Event(Base):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    realized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_call_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    agent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False, default=list)
    dropped_sweep: Mapped[int | None] = mapped_column(Integer)
    summarized_into: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_digest: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_call_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)


Index("ix_jobs_queued", Job.status, Job.role, Job.id, postgresql_where=text("status = 'queued'"))


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    segment: Mapped[str] = mapped_column(Text, nullable=False, default="all")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class Probe(Base):
    __tablename__ = "probes"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sweep: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="out_of_world")
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
