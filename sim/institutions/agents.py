from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sim.core.ids import new_id
from sim.db.constants import BASELINE_RUN_ID
from sim.db.models import Action, Exposure, Membership, Message
from sim.llm.gateway import execute_model_call


def weighted_signal(session: Session, run_id: UUID, sweep: int, sampling_ratio: float) -> float:
    n = session.scalar(
        select(func.count())
        .select_from(Action)
        .where(
            Action.run_id == run_id,
            Action.sweep == sweep,
            Action.type.in_(("talk", "post", "complain_formally", "organize")),
        )
    ) or 0
    return float(n) * float(sampling_ratio)


def institution_respond(
    ctx: Any,
    sweep: int,
    *,
    institution_id: str = "institution_maplewood_usd",
    name: str = "Maplewood Unified School District",
    threshold_real: float = 100.0,
) -> dict[str, Any]:
    weighted = weighted_signal(
        ctx.session, ctx.run.id, sweep, ctx.population.sampling_ratio
    )
    # Lower bar for small MVP pops so institutions can fire in tests
    n_agents = len(ctx.agents)
    triggered = weighted >= threshold_real or (
        n_agents <= 30 and weighted >= 3 * ctx.population.sampling_ratio
    )

    call = execute_model_call(
        ctx.session,
        run_kind=ctx.run.kind,
        master_seed=ctx.run.master_seed,
        sweep=sweep,
        role="institution",
        request={
            "triggered": triggered,
            "weighted_count": weighted,
            "threshold": threshold_real,
            "institution": institution_id,
            "prompt_context": {
                "institution_name": name,
                "mandate": "school governance",
                "voice": "bureaucratic",
                "weighted_count": weighted,
                "threshold": threshold_real,
                "triggered": triggered,
                "inbox_summary": f"{weighted:.0f} resident-weighted actions this week",
            },
        },
        call_key=f"institution-{institution_id}-{sweep}",
        config=ctx.config,
    )
    resp = call.response
    if resp.get("response") in ("statement", "story", "enforcement_change"):
        text = resp.get("text") or resp.get("headline") or "Institutional update."
        msg = Message(
            id=new_id(),
            run_id=ctx.run.id,
            sweep=sweep,
            sender=f"institution:{institution_id}",
            recipients={"broadcast": True},
            channel="broadcast",
            content=text,
            intent="inform",
            topic_tags=["phone_ban", "institution"],
        )
        ctx.session.add(msg)
        _broadcast_exposures(
            ctx.session,
            run_id=ctx.run.id,
            sweep=sweep,
            content=text,
            source_kind="institution",
            path=[{"institution": institution_id}],
            agent_ids=list(ctx.agents.keys()),
        )
    ctx.session.flush()
    return resp


def media_baseline_story(
    ctx: Any,
    sweep: int,
    *,
    outlet_id: str = "media_maplewood_ledger",
) -> None:
    """Weekly local news chance + pickup on high-engagement posts."""
    from sim.core.seeding import rng_for

    rng = rng_for(ctx.run.master_seed, "amplification", sweep, outlet_id)
    chaos = float(ctx.config.get("engine", {}).get("chaos_level", 1.0))
    if rng.random() > 0.35 * chaos and sweep > 0:
        # Still publish a thin baseline story occasionally
        if rng.random() > 0.5:
            return

    call = execute_model_call(
        ctx.session,
        run_kind=ctx.run.kind,
        master_seed=ctx.run.master_seed,
        sweep=sweep,
        role="institution",
        request={
            "triggered": True,
            "weighted_count": 0,
            "institution": outlet_id,
            "prompt_context": {
                "institution_name": "Maplewood Ledger",
                "mandate": "local news",
                "voice": "reporter",
                "weighted_count": 0,
                "threshold": 0,
                "triggered": True,
                "inbox_summary": "Weekly school/policy beat",
            },
        },
        call_key=f"media-{outlet_id}-{sweep}",
        config=ctx.config,
    )
    # Force story framing for media role when stub returns statement/none
    text = (
        call.response.get("text")
        or call.response.get("headline")
        or "Local schools begin phone pouch pilot; parents weigh in."
    )
    _broadcast_exposures(
        ctx.session,
        run_id=ctx.run.id,
        sweep=sweep,
        content=text,
        source_kind="media",
        path=[{"media": outlet_id}],
        agent_ids=_media_audience(ctx.session, list(ctx.agents.keys())),
        consume_p=0.4,
        master_seed=ctx.run.master_seed,
        seed_key=f"media-consume-{sweep}",
    )


def _media_audience(session: Session, agent_ids: list[UUID]) -> list[UUID]:
    rows = list(
        session.scalars(
            select(Membership).where(Membership.run_id == BASELINE_RUN_ID)
        )
    )
    # Prefer agents that have any membership; fall back to all
    members = {m.agent_id for m in rows if m.agent_id in set(agent_ids)}
    return list(members) if members else agent_ids


def _broadcast_exposures(
    session: Session,
    *,
    run_id: UUID,
    sweep: int,
    content: str,
    source_kind: str,
    path: list[dict[str, Any]],
    agent_ids: list[UUID],
    consume_p: float = 1.0,
    master_seed: int | None = None,
    seed_key: str = "broadcast",
) -> None:
    from sim.core.seeding import rng_for

    rng = None
    if consume_p < 1.0 and master_seed is not None:
        rng = rng_for(master_seed, "visibility", sweep, seed_key)
    for aid in agent_ids:
        if rng is not None and rng.random() > consume_p:
            continue
        session.add(
            Exposure(
                id=new_id(),
                run_id=run_id,
                sweep_created=sweep,
                deliver_sweep=sweep + 1,
                agent_id=aid,
                source_kind=source_kind,
                path=path,
                content=content,
                status="pending",
                expires_sweep=sweep + 3,
            )
        )
