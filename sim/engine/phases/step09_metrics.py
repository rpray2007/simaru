from __future__ import annotations

from sim.db.models import Metric
from sim.engine.context import RunContext


def run(ctx: RunContext, sweep: int) -> None:
    policy_id = ctx.policy.spec.get("id", "phone_ban_6_12")
    weights = []
    stances = []
    aware = 0.0
    engaged = 0.0
    total_w = 0.0
    for ar in ctx.agents.values():
        w = float(ar.agent.weight)
        total_w += w
        weights.append(w)
        st = ar.policy_stances.get(policy_id) or {}
        if st.get("aware"):
            aware += w
        stances.append(float(st.get("stance", 0.0)) * w)
        if st.get("engagement") in ("engaged", "mobilized"):
            engaged += w

    mean_stance = (sum(stances) / total_w) if total_w else 0.0
    awareness = (aware / total_w) if total_w else 0.0
    engaged_share = (engaged / total_w) if total_w else 0.0

    rows = [
        ("awareness", awareness),
        ("stance_mean", mean_stance),
        ("engaged_share", engaged_share),
        ("n_agents", float(len(ctx.agents))),
    ]
    for name, value in rows:
        ctx.session.add(
            Metric(
                run_id=ctx.run.id,
                sweep=sweep,
                segment="all",
                name=name,
                value=float(value),
            )
        )
    ctx.session.flush()
