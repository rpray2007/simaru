from sim.world.deltas import check_delta


def test_delta_requires_shape():
    assert check_delta({})["ok"] is False
    assert check_delta({"field": "enforcement.strictness", "to": 0.6})["ok"] is True


def test_delta_scale_guard():
    bad = check_delta(
        {"field": "enforcement.strictness", "from": 0.1, "to": 0.9},
        entity_fields={"enforcement": {"strictness": 0.1}},
    )
    assert bad["ok"] is False
    assert any("scale" in e for e in bad["errors"])


def test_retired_contradiction():
    bad = check_delta(
        {"field": "rules.phones", "to": "banned"},
        entity_fields={"retired": True},
    )
    assert bad["ok"] is False
