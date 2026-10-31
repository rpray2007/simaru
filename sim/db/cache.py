from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.core.errors import ReplayCacheMiss
from sim.core.ids import new_id
from sim.db.models import ModelCall


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def make_cache_key(
    *,
    model: str,
    model_digest: str,
    role: str,
    request: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str:
    payload = {
        "model": model,
        "model_digest": model_digest,
        "role": role,
        "request": request,
        "options": options or {},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def get_cached(session: Session, cache_key: str) -> ModelCall | None:
    return session.scalar(select(ModelCall).where(ModelCall.cache_key == cache_key))


def put_cached(
    session: Session,
    *,
    cache_key: str,
    role: str,
    model: str,
    model_digest: str,
    request: dict[str, Any],
    response: dict[str, Any],
    latency_ms: int = 0,
    attempts: int = 1,
    valid: bool = True,
) -> ModelCall:
    existing = get_cached(session, cache_key)
    if existing is not None:
        return existing
    row = ModelCall(
        id=new_id(),
        cache_key=cache_key,
        role=role,
        model=model,
        model_digest=model_digest,
        request=request,
        response=response,
        latency_ms=latency_ms,
        attempts=attempts,
        valid=valid,
    )
    session.add(row)
    session.flush()
    return row


def require_cached(session: Session, cache_key: str) -> ModelCall:
    hit = get_cached(session, cache_key)
    if hit is None:
        raise ReplayCacheMiss(f"Cache miss for key {cache_key[:16]}…")
    return hit
