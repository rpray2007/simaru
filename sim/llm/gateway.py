from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from sim.core.config import load_models
from sim.core.errors import ReplayCacheMiss
from sim.core.seeding import derive_seed
from sim.db import cache as model_cache
from sim.db.models import ModelCall
from sim.db.queue import enqueue_jobs, wait_for_jobs
from sim.llm.ollama import OllamaClient
from sim.llm.stub import StubLLM
from sim.llm.validation import apply_fallback, parse_and_validate
from sim.system1.client import StubSystem1Client
from sim.system1.openjev import OpenJevClient


def _model_entry(config: dict[str, Any], role: str) -> dict[str, Any]:
    models = load_models()
    name = config.get("models", {}).get(role)
    if not name:
        aliases = {
            "reflection": "system2",
            "narrative": "system2",
            "world_master_resolve": "world_master",
            "world_master_judgment": "world_master",
            "world_master_realize": "world_master",
            "institution": "institutions",
            "embed": "embeddings",
            "system1": "system1",
        }
        name = config.get("models", {}).get(aliases.get(role, role), "stub-llm")
    entry = models.get(name)
    if entry is None:
        raise KeyError(f"No model config for role {role} -> {name}")
    return {"name": name, **entry}


def execute_model_call(
    session: Session,
    *,
    run_kind: str,
    master_seed: int,
    sweep: int,
    role: str,
    request: dict[str, Any],
    call_key: str,
    config: dict[str, Any],
) -> ModelCall:
    entry = _model_entry(config, role)
    options = dict(entry.get("options") or {})
    options["seed"] = derive_seed(master_seed, "llm", sweep, role, call_key)
    cache_key = model_cache.make_cache_key(
        model=entry["model"],
        model_digest=entry.get("model_digest", "unknown"),
        role=role,
        request=request,
        options=options,
    )
    hit = model_cache.get_cached(session, cache_key)
    if hit is not None:
        return hit
    if run_kind == "replay":
        raise ReplayCacheMiss(cache_key)

    kind = entry.get("kind", "")
    # Inline path for stubs and for direct clients (MVP: engine may call models inline;
    # workers still support the same kinds for fan-out).
    if kind.startswith("stub") or kind in ("ollama_chat", "ollama_embed", "system_one"):
        response, latency_ms, attempts, valid = _execute_kind(
            kind=kind,
            role=role,
            request=request,
            master_seed=master_seed,
            sweep=sweep,
            call_key=call_key,
            entry=entry,
            options=options,
            config=config,
        )
        return model_cache.put_cached(
            session,
            cache_key=cache_key,
            role=role,
            model=entry["model"],
            model_digest=entry.get("model_digest", "unknown"),
            request={"request": request, "options": options},
            response=response,
            latency_ms=latency_ms,
            attempts=attempts,
            valid=valid,
        )

    job_ids = enqueue_jobs(
        session,
        [
            {
                "run_id": request.get("run_id"),
                "sweep": sweep,
                "phase": int(request.get("phase", 0)),
                "role": role,
                "payload": {
                    "request": request,
                    "options": options,
                    "call_key": call_key,
                    "model_name": entry["name"],
                },
                "cache_key": cache_key,
            }
        ],
    )
    session.commit()
    wait_for_jobs(session, job_ids)
    hit = model_cache.get_cached(session, cache_key)
    if hit is None:
        raise RuntimeError(f"Job finished but cache missing for {cache_key}")
    return hit


def _execute_kind(
    *,
    kind: str,
    role: str,
    request: dict[str, Any],
    master_seed: int,
    sweep: int,
    call_key: str,
    entry: dict[str, Any],
    options: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], int, int, bool]:
    if kind == "stub_system1" or (kind.startswith("stub") and role == "system1"):
        client = StubSystem1Client(master_seed=master_seed, sweep=sweep, agent_key=call_key)
        decisions = client.decide(request.get("state", ""), request.get("questions", {}))
        return {k: v.model_dump() for k, v in decisions.items()}, 0, 1, True

    if kind == "system_one":
        use_fixtures = bool(entry.get("use_fixtures") or config.get("models_use_fixtures"))
        fallback_fixtures = bool(entry.get("fallback_fixtures", True))
        client = OpenJevClient(
            base_url=entry.get("base_url"),
            model=entry.get("model", "jev-latest"),
            api_key=entry.get("api_key"),
            timeout_s=float(entry.get("timeout_s", 60)),
            use_fixtures=use_fixtures,
        )
        try:
            decisions = client.decide(request.get("state", ""), request.get("questions", {}))
            return {k: v.model_dump() for k, v in decisions.items()}, 0, 1, True
        except Exception:
            if use_fixtures or not fallback_fixtures:
                raise
            # Dev convenience: offline / missing key → fixtures (disable via fallback_fixtures: false)
            client.use_fixtures = True
            decisions = client.decide(request.get("state", ""), request.get("questions", {}))
            return {k: v.model_dump() for k, v in decisions.items()}, 0, 1, True

    if kind == "ollama_embed" or role == "embed":
        client = OllamaClient(
            base_url=entry.get("base_url", "http://localhost:11434"),
            model=entry.get("model", "nomic-embed-text"),
            model_digest=entry.get("model_digest", "pending"),
        )
        try:
            emb = client.embed(str(request.get("text", "")))
            return {"embedding": emb}, 0, 1, True
        except Exception:
            from sim.agents.memory import stub_embedding

            return {"embedding": stub_embedding(str(request.get("text", "")))}, 0, 1, True

    if kind == "ollama_chat":
        client = OllamaClient(
            base_url=entry.get("base_url", "http://localhost:11434"),
            model=entry.get("model", "llama3.2:3b"),
            model_digest=entry.get("model_digest", "pending"),
            options=entry.get("options") or {},
        )
        max_retries = int(config.get("llm", {}).get("max_retries", 2))
        return client.chat(
            role,
            request,
            seed=int(options.get("seed", 0)),
            max_retries=max_retries,
        )

    if kind.startswith("stub"):
        llm = StubLLM(
            master_seed=master_seed,
            model=entry.get("model", "stub-llm"),
            model_digest=entry.get("model_digest", "stub-llm-v1"),
        )
        raw = llm.complete(role, request, sweep=sweep, call_key=call_key)
        cleaned, valid, errors = parse_and_validate(
            role, raw, context=request.get("validation_context") or {}
        )
        if not valid and role in (
            "system2",
            "circle",
            "world_master",
            "world_master_resolve",
            "institution",
            "reflection",
        ):
            cleaned = apply_fallback(role, request)
            cleaned["_validation_errors"] = errors
            return cleaned, 0, 1, False
        return cleaned, 0, 1, valid

    raise ValueError(f"Unsupported model kind: {kind}")


def fanout_and_wait(
    session: Session,
    *,
    run_id: UUID,
    sweep: int,
    phase: int,
    jobs: list[dict[str, Any]],
    timeout_s: float = 300.0,
) -> list[Any]:
    if not jobs:
        return []
    prepared = [
        {
            "run_id": run_id,
            "sweep": sweep,
            "phase": phase,
            "role": j["role"],
            "payload": j["payload"],
            "cache_key": j["cache_key"],
        }
        for j in jobs
    ]
    ids = enqueue_jobs(session, prepared)
    session.commit()
    return wait_for_jobs(session, ids, timeout_s=timeout_s)
