from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.api.deps import get_db
from sim.api.why import build_why_chain
from sim.core.config import merge_config
from sim.db.models import Agent, Exposure, Metric, Place, Population, Run, WorldDelta
from sim.engine.context import create_run
from sim.engine.sweep import run as run_engine
from sim.places.maplewood import ensure_maplewood_pack
from sim.population.generate import build_synthetic_population

router = APIRouter()

# In-process run progress for WebSocket subscribers (MVP).
_RUN_EVENTS: dict[str, list[dict[str, Any]]] = {}
_RUN_LOCK = threading.Lock()


class PopulationCreate(BaseModel):
    place_id: UUID | None = None
    sampling_ratio: int = 100
    n_agents: int = 20
    seed: int = 17


class ExperimentCreate(BaseModel):
    name: str = "maplewood-phone-ban"
    n_agents: int = 20
    horizon_sweeps: int = 12
    seeds: list[int] = Field(default_factory=lambda: [17])
    master_seed: int | None = None


class EstimateRequest(BaseModel):
    n_agents: int = 200
    horizon_sweeps: int = 12
    seeds: int = 5
    workers: int = 4
    esc_rate: float = 0.25


def _notify(run_id: UUID, event: dict[str, Any]) -> None:
    key = str(run_id)
    with _RUN_LOCK:
        _RUN_EVENTS.setdefault(key, []).append(event)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/places")
def list_places(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ensure_maplewood_pack(db)
    places = list(db.scalars(select(Place).order_by(Place.slug)))
    return [
        {
            "id": str(p.id),
            "slug": p.slug,
            "version": p.version,
            "name": p.name,
            "status": p.status,
            "import_report": p.import_report,
        }
        for p in places
    ]


@router.get("/places/{place_id}")
def get_place(place_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    place = db.get(Place, place_id)
    if place is None:
        raise HTTPException(404, "place not found")
    return {
        "id": str(place.id),
        "slug": place.slug,
        "version": place.version,
        "name": place.name,
        "jurisdictions": place.jurisdictions,
        "sources": place.sources,
        "import_report": place.import_report,
        "status": place.status,
    }


@router.post("/populations")
def create_population(body: PopulationCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    place, _ = ensure_maplewood_pack(db)
    place_id = body.place_id or place.id
    cfg = merge_config()
    pop = build_synthetic_population(
        db,
        place_id=place_id,
        sampling_ratio=body.sampling_ratio,
        n_agents=body.n_agents,
        seed=body.seed,
        config=cfg,
    )
    db.commit()
    return {
        "id": str(pop.id),
        "status": pop.status,
        "checks": pop.checks,
        "sampling_ratio": pop.sampling_ratio,
    }


@router.get("/populations/{pop_id}")
def get_population(pop_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    pop = db.get(Population, pop_id)
    if pop is None:
        raise HTTPException(404, "population not found")
    n = db.scalar(select(Agent.id).where(Agent.population_id == pop.id).limit(1))
    count = len(list(db.scalars(select(Agent).where(Agent.population_id == pop.id))))
    return {
        "id": str(pop.id),
        "status": pop.status,
        "checks": pop.checks,
        "n_agents": count,
        "has_agents": n is not None,
    }


@router.post("/estimate")
def estimate(body: EstimateRequest) -> dict[str, Any]:
    cfg = merge_config()
    t_llm = float(cfg.get("estimate", {}).get("t_llm", 3.0))
    t_s1 = float(cfg.get("estimate", {}).get("t_s1", 0.3))
    s1_calls = body.n_agents * 10
    llm_calls = body.n_agents * body.esc_rate * 3 + body.n_agents * 0.05 / 4 + 20
    sec_per_sweep = (llm_calls * t_llm + s1_calls * t_s1) / max(1, body.workers)
    total = sec_per_sweep * body.horizon_sweeps * body.seeds
    return {
        "sec_per_sweep": round(sec_per_sweep, 1),
        "total_seconds": round(total, 1),
        "total_minutes": round(total / 60, 1),
        "s1_calls_per_sweep": s1_calls,
        "llm_calls_per_sweep": round(llm_calls, 1),
    }


@router.post("/experiments")
def create_experiment(body: ExperimentCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    seeds = body.seeds if body.master_seed is None else [body.master_seed]
    run_ids = []
    for seed in seeds:
        run = create_run(
            db,
            experiment=body.name,
            master_seed=seed,
            n_agents=body.n_agents,
            horizon_sweeps=body.horizon_sweeps,
        )
        run_ids.append(str(run.id))
    db.commit()

    # Kick first run in background thread (MVP single-process).
    if run_ids:
        rid = UUID(run_ids[0])

        def _bg() -> None:
            from sim.db.session import session_scope

            with session_scope() as session:
                _notify(rid, {"type": "status", "status": "running"})
                try:
                    ctx = run_engine(rid, session)
                    _notify(rid, {"type": "status", "status": ctx.run.status})
                except Exception as exc:  # noqa: BLE001
                    _notify(rid, {"type": "warning", "message": str(exc)})
                    _notify(rid, {"type": "status", "status": "failed"})

        threading.Thread(target=_bg, daemon=True).start()

    return {"experiment": body.name, "run_ids": run_ids}


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(Run).order_by(Run.created_at.desc()).limit(50)))
    return [
        {
            "id": str(r.id),
            "experiment": r.experiment,
            "status": r.status,
            "current_sweep": r.current_sweep,
            "master_seed": r.master_seed,
            "kind": r.kind,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return {
        "id": str(run.id),
        "experiment": run.experiment,
        "status": run.status,
        "current_sweep": run.current_sweep,
        "master_seed": run.master_seed,
        "config": run.config,
        "kind": run.kind,
        "horizon": run.config.get("engine", {}).get("horizon_sweeps"),
    }


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    run.pause_requested = True
    return {"status": "pause_requested"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    run.pause_requested = False
    run.status = "queued"
    db.commit()

    def _bg() -> None:
        from sim.db.session import session_scope

        with session_scope() as session:
            run_engine(run_id, session)

    threading.Thread(target=_bg, daemon=True).start()
    return {"status": "resuming"}


@router.get("/runs/{run_id}/sweeps/{sweep}/metrics")
def sweep_metrics(run_id: UUID, sweep: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(Metric).where(Metric.run_id == run_id, Metric.sweep == sweep)
        )
    )
    return [{"segment": r.segment, "name": r.name, "value": r.value} for r in rows]


@router.get("/runs/{run_id}/sweeps/{sweep}/map")
def sweep_map(run_id: UUID, sweep: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    agents = list(db.scalars(select(Agent).where(Agent.population_id == run.population_id)))
    from sim.db.models import AgentState

    points = []
    for a in agents:
        state = db.get(AgentState, {"run_id": run_id, "agent_id": a.id, "sweep": sweep})
        stances = (state.policy_stances if state else {}) or {}
        phone = stances.get("phone_ban_6_12") or {}
        points.append(
            {
                "agent_id": str(a.id),
                "lon": a.home_lon,
                "lat": a.home_lat,
                "stance": phone.get("stance", 0),
                "engagement": phone.get("engagement", "unaware"),
                "aware": phone.get("aware", False),
                "name": a.demographics.get("name"),
            }
        )
    return {"sweep": sweep, "points": points}


@router.get("/runs/{run_id}/sweeps/{sweep}/feed")
def sweep_feed(run_id: UUID, sweep: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    deltas = list(
        db.scalars(
            select(WorldDelta).where(WorldDelta.run_id == run_id, WorldDelta.sweep == sweep)
        )
    )
    exposures = list(
        db.scalars(
            select(Exposure).where(
                Exposure.run_id == run_id, Exposure.sweep_created == sweep
            ).limit(50)
        )
    )
    return {
        "deltas": [
            {
                "entity_id": d.entity_id,
                "change": d.change,
                "cause": d.cause,
                "status": d.status,
                "proposed_by": d.proposed_by,
            }
            for d in deltas
        ],
        "exposures": [
            {
                "agent_id": str(e.agent_id),
                "source_kind": e.source_kind,
                "content": e.content,
                "deliver_sweep": e.deliver_sweep,
            }
            for e in exposures
        ],
    }


@router.get("/runs/{run_id}/agents/{agent_id}")
def get_agent(
    run_id: UUID, agent_id: UUID, sweep: int | None = None, db: Session = Depends(get_db)
) -> dict[str, Any]:
    run = db.get(Run, run_id)
    agent = db.get(Agent, agent_id)
    if run is None or agent is None:
        raise HTTPException(404, "not found")
    s = sweep if sweep is not None else run.current_sweep
    from sim.db.models import AgentState, CircleContact, Memory

    state = db.get(AgentState, {"run_id": run_id, "agent_id": agent_id, "sweep": s})
    contacts = list(db.scalars(select(CircleContact).where(CircleContact.agent_id == agent_id)))
    memories = list(
        db.scalars(
            select(Memory)
            .where(Memory.run_id == run_id, Memory.agent_id == agent_id)
            .order_by(Memory.sweep.desc())
            .limit(20)
        )
    )
    return {
        "agent": {
            "id": str(agent.id),
            "tier": agent.tier,
            "demographics": agent.demographics,
            "narrative": agent.narrative,
            "anchors": agent.anchors,
            "voice": agent.voice,
        },
        "sweep": s,
        "state": {
            "slow": state.slow if state else None,
            "fast": state.fast if state else None,
            "policy_stances": state.policy_stances if state else None,
            "tier": state.tier if state else agent.tier,
        },
        "circle": [
            {"key": c.contact_key, "label": c.label, "sphere": c.sphere} for c in contacts
        ],
        "memories": [
            {"sweep": m.sweep, "type": m.type, "content": m.content, "importance": m.importance}
            for m in memories
        ],
    }


@router.get("/runs/{run_id}/agents/{agent_id}/why")
def agent_why(
    run_id: UUID, agent_id: UUID, sweep: int = 0, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return build_why_chain(db, run_id, agent_id, sweep)


@router.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: UUID) -> None:
    await websocket.accept()
    key = str(run_id)
    sent = 0
    try:
        while True:
            with _RUN_LOCK:
                events = list(_RUN_EVENTS.get(key, []))
            while sent < len(events):
                await websocket.send_json(events[sent])
                sent += 1
            # Also push DB status periodically
            from sim.db.session import session_scope

            with session_scope() as session:
                run = session.get(Run, run_id)
                if run:
                    await websocket.send_json(
                        {
                            "type": "sweep_done" if run.status == "running" else "status",
                            "status": run.status,
                            "current_sweep": run.current_sweep,
                        }
                    )
                    if run.status in ("completed", "failed", "cancelled"):
                        break
            import asyncio

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
