from sim.llm.schemas import System2Output
from sim.llm.validation import apply_fallback, parse_and_validate, validate_system2_semantics, voice_ok


def test_voice_bans_assistant_phrases():
    ok, errs = voice_ok("As an AI I think this is multifaceted.")
    assert not ok
    assert any("banned" in e or "multifaceted" in e for e in errs)


def test_system2_drops_invalid_talk_target():
    out = System2Output.model_validate(
        {
            "interpretation": "Noticed the ban.",
            "emotion": {"label": "annoyed", "intensity": 0.4},
            "importance": 6,
            "actions": [
                {"type": "talk", "to": "stranger", "content": "Hey", "channel": "text", "intent": "inform"},
                {"type": "talk", "to": "household", "content": "Hey", "channel": "in_person", "intent": "inform"},
            ],
            "reasoning": "test",
        }
    )
    cleaned, errors = validate_system2_semantics(out, roster_keys=["household"], engagement="mild")
    assert len(cleaned.actions) == 1
    assert cleaned.actions[0].to == "household"
    assert errors


def test_parse_and_validate_and_fallback():
    raw = {
        "interpretation": "x",
        "emotion": {"label": "ok", "intensity": 0.2},
        "importance": 5,
        "actions": [],
        "reasoning": "ok",
    }
    data, valid, _ = parse_and_validate("system2", raw)
    assert valid
    assert data["importance"] == 5
    fb = apply_fallback("system2", {})
    assert fb.get("_fallback") is True
