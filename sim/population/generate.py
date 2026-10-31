from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from sim.agents.profile import default_fast, default_slow
from sim.core.ids import new_id
from sim.core.seeding import rng_for
from sim.db.constants import BASELINE_RUN_ID
from sim.db.models import Agent, CircleContact, Context, Membership, Population
from sim.llm.gateway import execute_model_call
from sim.population.checks import run_population_checks

OCCUPATIONS = [
    ("teacher", "school"),
    ("nurse", "hospital"),
    ("retail clerk", "retail"),
    ("software engineer", "office"),
    ("parent caregiver", "home"),
    ("student", "school"),
    ("construction worker", "trades"),
    ("restaurant worker", "food"),
]

FIRST = ["Alex", "Jordan", "Sam", "Riley", "Casey", "Morgan", "Avery", "Quinn", "Jamie", "Taylor"]
LAST = ["Lee", "Nguyen", "Garcia", "Patel", "Kim", "Brown", "Murphy", "Singh", "Lopez", "Chen"]


def build_synthetic_population(
    session: Session,
    *,
    place_id: UUID,
    sampling_ratio: int = 100,
    n_agents: int = 20,
    seed: int = 17,
    full_tier_share: float = 0.05,
    config: dict[str, Any] | None = None,
    run_burn_in: bool = False,
) -> Population:
    """MVP population: synthetic Maplewood residents with narratives and rosters."""
    cfg = config or {}
    pop = Population(
        id=new_id(),
        place_id=place_id,
        sampling_ratio=sampling_ratio,
        generator_config={
            "mode": "synthetic",
            "n_agents": n_agents,
            "full_tier_share": full_tier_share,
        },
        seed=seed,
        status="building",
    )
    session.add(pop)
    session.flush()

    contexts = _create_contexts(session, place_id)
    rng = rng_for(seed, "population", 0, "skeleton")
    agents: list[Agent] = []
    n_full = max(1, int(round(n_agents * full_tier_share)))

    for i in range(n_agents):
        age = int(rng.integers(14, 78))
        is_student = age < 18
        occ, sector = ("student", "school") if is_student else OCCUPATIONS[int(rng.integers(0, len(OCCUPATIONS) - 1))]
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 3) % len(LAST)]}"
        sex = "F" if rng.random() < 0.5 else "M"
        education = "some_college" if age >= 22 else "in_school"
        income = int(rng.choice([25000, 45000, 65000, 90000, 120000]))
        tier = "full" if i < n_full else "standard"
        demo = {
            "name": name,
            "age": age,
            "sex": sex,
            "race_eth": str(rng.choice(["white", "black", "hispanic", "asian", "other"])),
            "education": education,
            "income": income,
            "occupation": occ,
            "household": {"size": int(rng.integers(1, 5)), "has_school_child": age >= 30 and rng.random() < 0.45},
            "neighborhood": str(rng.choice(["Northside", "Downtown", "Riverside", "Hillcrest"])),
        }
        traits = {
            "openness": float(rng.uniform(0.1, 0.9)),
            "conscientiousness": float(rng.uniform(0.1, 0.9)),
            "extraversion": float(rng.uniform(0.1, 0.9)),
            "agreeableness": float(rng.uniform(0.1, 0.9)),
            "neuroticism": float(rng.uniform(0.1, 0.9)),
        }
        narrative_call = execute_model_call(
            session,
            run_kind="run",
            master_seed=seed,
            sweep=0,
            role="narrative",
            request={"demographics": demo, "traits": traits},
            call_key=f"narrative-{i}",
            config=cfg or {"models": {"narrative": "stub-llm", "system2": "stub-llm"}},
        )
        narrative = narrative_call.response
        agent = Agent(
            id=new_id(),
            population_id=pop.id,
            weight=float(sampling_ratio),
            tier=tier,
            is_synthetic_tail=False,
            demographics=demo,
            traits=traits,
            values={"ranked": ["family", "security", "fairness"]},
            voice=narrative.get("voice") or {},
            narrative=narrative.get("biography") or "",
            anchors=list(narrative.get("anchors") or [f"Age {age}", f"Works as {occ}"]),
            footprint={
                "roles": ["student"] if is_student else ["worker"],
                "places": ["school_maplewood_high" if age >= 14 and age <= 18 else "school_maplewood_middle"]
                if is_student or demo["household"].get("has_school_child")
                else [],
                "institutions": ["institution_maplewood_usd"],
                "workplace": "workplace_hospital" if sector == "hospital" else None,
            },
            home_lon=-74.25 + float(rng.uniform(-0.03, 0.03)),
            home_lat=40.75 + float(rng.uniform(-0.03, 0.03)),
            donors={"synthetic": True},
            civic_baseline=float(rng.uniform(0.2, 0.85)),
            attention_baseline=float(rng.uniform(4.0, 8.0)),
        )
        session.add(agent)
        session.flush()
        agents.append(agent)
        _assign_memberships(session, agent, contexts, is_student=is_student, has_child=bool(demo["household"].get("has_school_child")))
        _create_roster(session, agent, narrative.get("roster_seeds") or [], contexts)

    pop.status = "checking"
    session.flush()
    checks = run_population_checks(agents)
    pop.checks = checks
    pop.baseline_sweep = -1
    pop.status = "frozen" if checks.get("pass") else "failed"
    if run_burn_in:
        # Burn-in is owned by the engine; mark placeholder.
        pop.baseline_sweep = int(cfg.get("engine", {}).get("burn_in_sweeps", 6)) - 1
    session.flush()
    return pop


def _create_contexts(session: Session, place_id: UUID) -> dict[str, Context]:
    specs = [
        ("school_students", "school_students", "Maplewood Students", "school_maplewood_high"),
        ("school_parents", "school_parents", "Maplewood Parents", "school_maplewood_high"),
        ("workplace_hospital", "workplace", "Hospital Staff", "workplace_hospital"),
        ("online_parents", "online_group", "Maplewood Parents Online", "group_parents_online"),
        ("media_audience", "media_audience", "Ledger Readers", "media_maplewood_ledger"),
    ]
    out: dict[str, Context] = {}
    for key, kind, name, entity_id in specs:
        ctx = Context(
            id=new_id(),
            place_id=place_id,
            run_id=BASELINE_RUN_ID,
            created_sweep=-1,
            kind=kind,
            entity_id=entity_id,
            name=name,
            real_size=500,
            params={"feed_probability": 0.35},
        )
        session.add(ctx)
        out[key] = ctx
    session.flush()
    return out


def _assign_memberships(
    session: Session,
    agent: Agent,
    contexts: dict[str, Context],
    *,
    is_student: bool,
    has_child: bool,
) -> None:
    age = int(agent.demographics.get("age", 30))
    if is_student:
        session.add(
            Membership(
                context_id=contexts["school_students"].id,
                agent_id=agent.id,
                from_sweep=-1,
                run_id=BASELINE_RUN_ID,
                role="student",
            )
        )
    if has_child or (30 <= age <= 55):
        session.add(
            Membership(
                context_id=contexts["school_parents"].id,
                agent_id=agent.id,
                from_sweep=-1,
                run_id=BASELINE_RUN_ID,
                role="parent",
            )
        )
        session.add(
            Membership(
                context_id=contexts["online_parents"].id,
                agent_id=agent.id,
                from_sweep=-1,
                run_id=BASELINE_RUN_ID,
                role="member",
            )
        )
    if agent.demographics.get("occupation") == "nurse":
        session.add(
            Membership(
                context_id=contexts["workplace_hospital"].id,
                agent_id=agent.id,
                from_sweep=-1,
                run_id=BASELINE_RUN_ID,
                role="employee",
            )
        )
    session.add(
        Membership(
            context_id=contexts["media_audience"].id,
            agent_id=agent.id,
            from_sweep=-1,
            run_id=BASELINE_RUN_ID,
            role="audience",
        )
    )


def _create_roster(
    session: Session,
    agent: Agent,
    seeds: list[dict[str, Any]],
    contexts: dict[str, Context],
) -> None:
    if not seeds:
        seeds = [
            {"label": "Household", "sphere": "household", "description": "Household", "stance_tendency": "mixed"},
            {"label": "Friend", "sphere": "close", "description": "Close friend", "stance_tendency": "agree"},
        ]
    for i, seed in enumerate(seeds):
        sphere = seed.get("sphere", "close")
        key = sphere if i == 0 else f"{sphere}_{i}"
        ctx_id = None
        if sphere == "work_school":
            ctx_id = contexts.get("workplace_hospital", contexts["school_students"]).id
        session.add(
            CircleContact(
                id=new_id(),
                agent_id=agent.id,
                contact_key=key,
                label=seed.get("label", key),
                sphere=sphere,
                context_id=ctx_id,
                stance_tendency=seed.get("stance_tendency"),
                description=seed.get("description", ""),
                aggregate=sphere in ("work_school", "community", "online"),
            )
        )


def initial_agent_state(agent: Agent) -> dict[str, Any]:
    return {
        "tier": agent.tier,
        "slow": default_slow(),
        "fast": default_fast(attention=agent.attention_baseline, stress=0.2),
        "policy_stances": {},
    }
