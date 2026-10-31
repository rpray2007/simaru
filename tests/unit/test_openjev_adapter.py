from sim.llm.gateway import _execute_kind
from sim.system1.openjev import OpenJevClient
from sim.system1.questions import notice_route_v1_openjev, to_openjev_questions


def test_openjev_fixture_phone_route():
    client = OpenJevClient(use_fixtures=True)
    questions = {
        "notices": {"options": ["yes", "no"]},
        "valence": {"options": ["negative", "neutral", "positive"]},
        "arousal": {"options": ["low", "medium", "high"]},
        "route": {"options": ["ignore", "habit", "escalate"]},
        "habit_action": {"options": ["none", "grumble at home"]},
        "relevance": {"options": ["not me", "someone close", "me directly"]},
    }
    out = client.decide("Agent hears about a phone ban at school.", questions)
    assert out["route"].value == "escalate"
    assert out["notices"].value == "yes"
    assert out["notices"].probs["yes"] >= 0.5


def test_openjev_fixture_quiet_ignore():
    client = OpenJevClient(use_fixtures=True)
    out = client.decide("A quiet afternoon with nothing urgent.", notice_route_v1_openjev())
    assert out["route"].value == "ignore"
    assert out["notices"].value == "no"


def test_to_openjev_questions_noul_for_notices():
    converted = to_openjev_questions({"notices": {"type": "choice", "options": ["yes", "no"]}})
    assert converted["notices"]["type"] == "noul"


def test_notice_route_v1_openjev_shape():
    qs = notice_route_v1_openjev()
    assert qs["notices"]["type"] == "noul"
    assert "escalate" in qs["route"]["criteria"]
    assert "instructions" in qs["valence"]


def test_gateway_system_one_fixtures():
    response, _, attempts, valid = _execute_kind(
        kind="system_one",
        role="system1",
        request={
            "state": "Agent hears about a phone ban at school.",
            "questions": notice_route_v1_openjev(),
        },
        master_seed=1,
        sweep=0,
        call_key="t1",
        entry={
            "kind": "system_one",
            "model": "openjev-fixtures",
            "use_fixtures": True,
            "base_url": "https://api.openjev.sh/v1/systemone",
        },
        options={},
        config={},
    )
    assert valid and attempts == 1
    assert response["route"]["value"] == "escalate"
    assert response["notices"]["value"] == "yes"


def test_hosted_without_key_uses_fixtures():
    client = OpenJevClient(base_url="https://api.typesafe.ai/v1/systemone", api_key="")
    out = client.decide("phone ban news", notice_route_v1_openjev())
    assert out["route"].value == "escalate"
