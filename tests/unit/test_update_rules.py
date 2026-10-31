from sim.agents.profile import PolicyStance
from sim.agents.update_rules import apply_decay, apply_gut_update, engagement_level


def test_gut_update_bounded():
    s = PolicyStance(policy_id="p")
    s2 = apply_gut_update(s, valence=-1.0)
    assert -0.5 <= s2.stance - s.stance <= 0.5
    assert s2.stance_source == "gut"
    assert s2.aware is True


def test_engagement_clamp_and_civic_cap():
    s = PolicyStance(policy_id="p", aware=True, stance=3.0, salience=1.0, engagement="mild")
    level = engagement_level(s, civic_baseline=0.3)
    assert level in ("mild", "engaged", "indifferent")
    assert level != "mobilized"


def test_decay():
    fast = {"mood": 0.8, "stress": 0.2, "concerns": [{"topic": "phones", "salience": 0.1}], "attention": 6}
    out = apply_decay(fast)
    assert abs(out["mood"]) < abs(fast["mood"]) or out["mood"] == 0.4
