from sim.core.config import config_hash, merge_config, model_manifest


def test_merge_and_hash():
    cfg = merge_config(run_overrides={"engine": {"horizon_sweeps": 4}})
    assert cfg["engine"]["horizon_sweeps"] == 4
    assert "system1" in cfg
    h1 = config_hash(cfg)
    h2 = config_hash(cfg)
    assert h1 == h2
    manifest = model_manifest(cfg)
    assert "system1" in manifest
    assert manifest["system1"]["name"] == "typesafe-hosted"
    assert manifest["system1"]["model"] == "jev-latest"
    assert manifest["system1"]["model_digest"]
