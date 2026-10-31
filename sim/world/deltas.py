from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from sim.core.ids import new_id
from sim.db.models import WorldDelta

# Max absolute weekly change for numeric fields (scale check).
FIELD_SCALE_LIMITS: dict[str, float] = {
    "enforcement.strictness": 0.5,
    "enrollment": 50,
    "customers_weekly": 200,
}


def check_delta(change: dict[str, Any], *, entity_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Schema / contradiction / scale / cause pre-checks before commit."""
    results: dict[str, Any] = {"ok": True, "errors": []}
    if not change:
        results["ok"] = False
        results["errors"].append("empty_change")
        return results

    if change.get("retire"):
        return results

    if "create" in change:
        create = change["create"]
        if not isinstance(create, dict) or "kind" not in create or "name" not in create:
            results["ok"] = False
            results["errors"].append("create_missing_fields")
        return results

    field = change.get("field")
    if field is None and "to" not in change:
        results["ok"] = False
        results["errors"].append("missing_field_or_to")
        return results

    if field and entity_fields is not None:
        # Contradiction: retired entity cannot change — signaled by fields.retired
        if entity_fields.get("retired"):
            results["ok"] = False
            results["errors"].append("retired_entity")

    if field and "to" in change and isinstance(change["to"], (int, float)):
        limit = FIELD_SCALE_LIMITS.get(field)
        if limit is not None:
            prev = change.get("from")
            if prev is None and entity_fields is not None:
                parts = field.split(".")
                cursor: Any = entity_fields
                for p in parts:
                    cursor = (cursor or {}).get(p) if isinstance(cursor, dict) else None
                prev = cursor
            if prev is not None and abs(float(change["to"]) - float(prev)) > limit:
                if not change.get("shock_cited"):
                    results["ok"] = False
                    results["errors"].append(f"scale_exceeded:{field}")

    return results


def commit_delta(
    session: Session,
    *,
    run_id: UUID,
    sweep: int,
    entity_id: str,
    change: dict[str, Any],
    cause: list[str],
    proposed_by: str,
    confidence: float | None = None,
    description_update: str | None = None,
    model_call_id: UUID | None = None,
    entity_fields: dict[str, Any] | None = None,
) -> WorldDelta:
    if not cause:
        raise ValueError("delta requires non-empty cause")
    checks = check_delta(change, entity_fields=entity_fields)
    status = "committed" if checks.get("ok") else "rejected"
    row = WorldDelta(
        id=new_id(),
        run_id=run_id,
        sweep=sweep,
        entity_id=entity_id,
        change=change,
        description_update=description_update,
        cause=cause,
        proposed_by=proposed_by,
        confidence=confidence,
        status=status,
        check_results=checks,
        model_call_id=model_call_id,
    )
    session.add(row)
    session.flush()
    return row
