from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.core.ids import new_id
from sim.db.constants import BASELINE_RUN_ID
from sim.db.models import Place, PolicyPackage, WorldEntity

MAPLEWOOD_SLUG = "maplewood"
PHONE_BAN_SLUG = "phone_ban_6_12"


def phone_ban_spec() -> dict[str, Any]:
    return {
        "id": PHONE_BAN_SLUG,
        "version": 1,
        "jurisdiction": "maplewood_usd",
        "announce_sweep": 0,
        "effective_sweep": 1,
        "rules": [
            {
                "id": "all_day_ban",
                "applies_to": {"entity_kind": "school", "grades": list(range(6, 13))},
                "effect": {"set_field": "rules.phones", "value": "locked_pouch_all_day"},
            }
        ],
        "exemptions": [],
        "mechanics": [{"per_agent": "phone_ban.daily_impact"}],
        "judgment_hooks": [
            {
                "id": "enforcement_strictness",
                "per": "school",
                "sweeps": "every",
                "question": "How strictly is the ban enforced this week?",
                "output_field": "enforcement.strictness",
            }
        ],
        "announcements": [
            {
                "sweep": 0,
                "via": ["institution:maplewood_usd", "media:maplewood_ledger"],
                "text": (
                    "Maplewood Unified announces an all-day phone ban for grades 6–12, "
                    "starting next week."
                ),
            }
        ],
        "open_mode_limits": {
            "allowed_amendments": ["add_exemption", "add_contact_channel", "change_enforcement"]
        },
        "outcome_parameters": {"learning_effect": "none"},
    }


def ensure_maplewood_pack(session: Session) -> tuple[Place, PolicyPackage]:
    place = session.scalar(
        select(Place).where(Place.slug == MAPLEWOOD_SLUG, Place.version == 1)
    )
    if place is None:
        place = Place(
            id=new_id(),
            slug=MAPLEWOOD_SLUG,
            version=1,
            name="Maplewood",
            boundary_geojson={
                "type": "Polygon",
                "coordinates": [[[-74.3, 40.7], [-74.2, 40.7], [-74.2, 40.8], [-74.3, 40.8], [-74.3, 40.7]]],
            },
            jurisdictions=[
                {"id": "maplewood_usd", "kind": "school_district", "name": "Maplewood Unified"},
                {"id": "maplewood_city", "kind": "municipality", "name": "City of Maplewood"},
            ],
            sources=[{"layer": "world_brief", "source": "hand-authored MVP", "as_of": "2026-10-11"}],
            import_report={"mode": "world_brief", "confidence": "medium"},
            status="approved",
        )
        session.add(place)
        session.flush()
        _seed_canon(session, place.id)

    policy = session.scalar(
        select(PolicyPackage).where(
            PolicyPackage.slug == PHONE_BAN_SLUG, PolicyPackage.version == 1
        )
    )
    if policy is None:
        policy = PolicyPackage(
            id=new_id(),
            slug=PHONE_BAN_SLUG,
            version=1,
            place_id=place.id,
            spec=phone_ban_spec(),
        )
        session.add(policy)
        session.flush()
    return place, policy


def _seed_canon(session: Session, place_id: UUID) -> None:
    entities = [
        ("school_maplewood_middle", "school", "Maplewood Middle School", {
            "grades": [6, 7, 8],
            "enrollment": 720,
            "rules": {"phones": "allowed"},
            "enforcement": {"strictness": 0.5},
        }),
        ("school_maplewood_high", "school", "Maplewood High School", {
            "grades": [9, 10, 11, 12],
            "enrollment": 1100,
            "rules": {"phones": "allowed"},
            "enforcement": {"strictness": 0.5},
        }),
        ("institution_maplewood_usd", "institution", "Maplewood Unified School District", {
            "jurisdiction": "maplewood_usd",
            "functions": ["policy", "enforcement"],
            "thresholds": {"formal_complaints": 100},
            "voice": "bureaucratic",
            "contact_channels": ["formal"],
        }),
        ("media_maplewood_ledger", "media", "Maplewood Ledger", {
            "outlet_type": "local_news",
            "audience_real": 8000,
            "slant": "neutral",
            "publishing_schedule": "weekly",
        }),
        ("group_parents_online", "group", "Maplewood Parents Online", {
            "platform": "facebook",
            "members_real": 1200,
            "activity": 0.4,
            "norms": "civil",
        }),
        ("workplace_hospital", "workplace", "Maplewood General Hospital", {
            "sector": "health",
            "employees_real": 900,
            "hours": "24/7",
            "shifts": ["day", "night"],
        }),
    ]
    for entity_id, kind, name, fields in entities:
        session.add(
            WorldEntity(
                place_id=place_id,
                entity_id=entity_id,
                run_id=BASELINE_RUN_ID,
                sweep=-1,
                kind=kind,
                name=name,
                fields=fields,
                description=f"{name} in Maplewood.",
                invented=True,
                sources=[{"source": "world_brief"}],
            )
        )
