from sim.core.ids import new_id
from sim.db.models import Action
from sim.engine.sweep import run_experiment
from sim.world.resolver import batch_by_entity, entity_capacity, resolve_collisions
from tests.conftest import requires_postgres


def test_capacity_and_batching_unit():
    assert entity_capacity("x", {"capacity": 2}) == 2
    groups = batch_by_entity(
        [
            {"action_id": "a", "target_entity": "school"},
            {"action_id": "b", "target_entity": "school"},
            {"action_id": "c", "target_entity": "hospital"},
        ]
    )
    assert len(groups["school"]) == 2
    assert len(groups["hospital"]) == 1


@requires_postgres
def test_collision_respects_capacity(db_session):
    ctx = run_experiment(db_session, master_seed=99, n_agents=8, horizon_sweeps=1)
    # Fabricate more open-ended intents than capacity against one school
    open_ended = []
    agent_ids = list(ctx.agents.keys())
    for i in range(6):
        aid = agent_ids[i % len(agent_ids)]
        row = Action(
            id=new_id(),
            run_id=ctx.run.id,
            sweep=0,
            agent_id=aid,
            source="system2",
            type="adapt_behavior",
            intent_text=f"ask for exception {i}",
            params={},
            validation={"ok": True},
            resolver="world_master",
        )
        db_session.add(row)
        db_session.flush()
        open_ended.append(
            {
                "action_id": f"ask-{i}",
                "agent_id": str(aid),
                "intent_text": f"ask for exception {i}",
                "agent_summary": "tester",
                "target_entity": "school_maplewood_high",
                "percentile": 50 + i,
                "_row": row,
                "_ar": ctx.agents[aid],
            }
        )
    results = resolve_collisions(
        ctx,
        0,
        open_ended,
        entity_fields={"school_maplewood_high": {"capacity": 3}},
    )
    granted = [r for r in results if r["status"] in ("granted", "done", "partial")]
    refused = [r for r in results if r["status"] == "refused"]
    assert len(granted) <= 3
    assert len(refused) >= 3
