from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sim.agents.profile import PolicyStance, default_fast, default_slow
from sim.core.config import config_hash, merge_config, model_manifest
from sim.core.ids import new_id
from sim.db.models import Agent, AgentState, PolicyPackage, Population, Run
from sim.engine.types import Input
from sim.places.maplewood import ensure_maplewood_pack
from sim.population.generate import build_synthetic_population


@dataclass
class AgentRuntime:
    agent: Agent
    slow: dict[str, Any]
    fast: dict[str, Any]
    policy_stances: dict[str, Any]
    tier: str
    inputs: list[Input] = field(default_factory=list)
    escalated_inputs: list[Input] = field(default_factory=list)
    pending_intents: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RunContext:
    session: Session
    run: Run
    population: Population
    policy: PolicyPackage
    config: dict[str, Any]
    agents: dict[UUID, AgentRuntime]
    start_sweep: int
    horizon: int

    @classmethod
    def load(cls, session: Session, run_id: UUID) -> RunContext:
        run = session.get(Run, run_id)
        if run is None:
            raise KeyError(run_id)
        population = session.get(Population, run.population_id)
        policy = session.get(PolicyPackage, run.policy_package_id)
        if population is None or policy is None:
            raise KeyError("population or policy missing")
        agent_rows = list(
            session.scalars(
                select(Agent)
                .where(Agent.population_id == population.id)
                .order_by(Agent.id)
            )
        )
        agents: dict[UUID, AgentRuntime] = {}
        for a in agent_rows:
            state = session.get(
                AgentState, {"run_id": run.id, "agent_id": a.id, "sweep": run.current_sweep}
            )
            if state is None and run.current_sweep >= 0:
                # find latest
                state = session.scalar(
                    select(AgentState)
                    .where(AgentState.run_id == run.id, AgentState.agent_id == a.id)
                    .order_by(AgentState.sweep.desc())
                    .limit(1)
                )
            agents[a.id] = AgentRuntime(
                agent=a,
                slow=(state.slow if state else default_slow()),
                fast=(state.fast if state else default_fast(attention=a.attention_baseline)),
                policy_stances=(state.policy_stances if state else {}),
                tier=(state.tier if state else a.tier),
            )
        return cls(
            session=session,
            run=run,
            population=population,
            policy=policy,
            config=run.config,
            agents=agents,
            start_sweep=run.current_sweep + 1,
            horizon=int(run.config.get("engine", {}).get("horizon_sweeps", 12)),
        )

    def pause_requested(self) -> bool:
        self.session.refresh(self.run)
        return bool(self.run.pause_requested)

    def set_status(self, status: str) -> None:
        self.run.status = status
        self.session.flush()

    def commit_sweep(self, sweep: int) -> None:
        for ar in self.agents.values():
            self.session.add(
                AgentState(
                    run_id=self.run.id,
                    agent_id=ar.agent.id,
                    sweep=sweep,
                    tier=ar.tier,
                    slow=ar.slow,
                    fast=ar.fast,
                    policy_stances=ar.policy_stances,
                )
            )
        self.run.current_sweep = sweep
        self.session.flush()

    def policy_stance(self, agent_id: UUID, policy_id: str) -> PolicyStance:
        ar = self.agents[agent_id]
        raw = ar.policy_stances.get(policy_id)
        if raw is None:
            return PolicyStance(policy_id=policy_id)
        return PolicyStance.model_validate(raw)

    def set_policy_stance(self, agent_id: UUID, stance: PolicyStance) -> None:
        self.agents[agent_id].policy_stances[stance.policy_id] = stance.model_dump()


def create_run(
    session: Session,
    *,
    experiment: str = "maplewood-phone-ban",
    master_seed: int = 17,
    n_agents: int = 20,
    horizon_sweeps: int = 12,
    kind: str = "run",
    config_overrides: dict[str, Any] | None = None,
    population_id: UUID | None = None,
) -> Run:
    place, policy = ensure_maplewood_pack(session)
    cfg = merge_config(
        experiment={
            "engine": {"horizon_sweeps": horizon_sweeps},
            "population": {"sampling_ratio": 100, "full_tier_share": 0.05},
        },
        run_overrides=config_overrides,
    )
    if population_id is None:
        pop = build_synthetic_population(
            session,
            place_id=place.id,
            n_agents=n_agents,
            seed=master_seed,
            full_tier_share=float(cfg.get("population", {}).get("full_tier_share", 0.05)),
            config=cfg,
        )
    else:
        pop = session.get(Population, population_id)
        if pop is None:
            raise KeyError(population_id)

    run = Run(
        id=new_id(),
        experiment=experiment,
        population_id=pop.id,
        policy_package_id=policy.id,
        master_seed=master_seed,
        config=cfg,
        config_hash=config_hash(cfg),
        model_manifest=model_manifest(cfg),
        status="queued",
        current_sweep=-1,
        kind=kind,
    )
    session.add(run)
    session.flush()
    return run
