from sim.system1.client import Decision
from sim.system1.routing import route_decision


def test_notice_no_ignore():
    answers = {
        "notices": Decision(value="no", confidence=0.9),
        "route": Decision(value="escalate", confidence=0.9),
    }
    route, by = route_decision(answers, input_data={}, agent={})
    assert route == "ignore"
    assert by is None


def test_impact_trigger():
    answers = {
        "notices": Decision(value="yes", confidence=0.9),
        "route": Decision(value="habit", confidence=0.9),
        "arousal": Decision(value="low", confidence=0.9),
        "valence": Decision(value="neutral", confidence=0.9),
    }
    route, by = route_decision(
        answers, input_data={"impact_magnitude": 0.7}, agent={}
    )
    assert route == "escalate"
    assert by == "trigger:impact"
