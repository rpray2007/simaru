from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.core.ids import new_id
from sim.db.models import Memory


def stub_embedding(text: str, dim: int = 768) -> list[float]:
    """Deterministic pseudo-embedding for stub mode (no model call)."""
    vals = [0.0] * dim
    for i, ch in enumerate(text.encode("utf-8")):
        vals[i % dim] += (ch / 255.0) * 0.01
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [v / norm for v in vals]


def write_memory(
    session: Session,
    *,
    run_id: UUID,
    agent_id: UUID,
    sweep: int,
    type: str,
    content: str,
    importance: int,
    valence: float,
    source: str | None = None,
    policy_id: str | None = None,
) -> Memory:
    row = Memory(
        id=new_id(),
        run_id=run_id,
        agent_id=agent_id,
        sweep=sweep,
        type=type,
        content=content,
        source=source,
        importance=max(1, min(10, importance)),
        valence=max(-1.0, min(1.0, valence)),
        policy_id=policy_id,
        embedding=stub_embedding(content),
    )
    session.add(row)
    return row


def retrieve_memories(
    session: Session,
    *,
    run_id: UUID,
    agent_id: UUID,
    query: str,
    k: int = 8,
    anchors: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(Memory)
            .where(
                Memory.run_id == run_id,
                Memory.agent_id == agent_id,
                Memory.dropped_sweep.is_(None),
            )
            .order_by(Memory.sweep.desc())
            .limit(200)
        )
    )
    q_emb = stub_embedding(query)

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    scored: list[tuple[float, Memory]] = []
    for m in rows:
        recency = 0.85 ** max(0, (rows[0].sweep - m.sweep) if rows else 0)
        sim = cosine(q_emb, m.embedding or stub_embedding(m.content))
        score = recency + (m.importance / 10.0) + sim
        scored.append((score, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for a in anchors or []:
        out.append({"sweep": -1, "content": a, "importance": 10, "type": "anchor"})
    for _, m in scored[:k]:
        out.append(
            {
                "id": str(m.id),
                "sweep": m.sweep,
                "content": m.content,
                "importance": m.importance,
                "type": m.type,
            }
        )
    return out
