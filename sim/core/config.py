from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from sim.core.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "defaults.yaml"
MODELS_CONFIG_PATH = REPO_ROOT / "config" / "models.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config not found: {path}")
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return data


def load_models(path: Path | None = None) -> dict[str, Any]:
    return load_yaml(path or MODELS_CONFIG_PATH)


def merge_config(
    *,
    defaults_path: Path | None = None,
    place_overrides: dict[str, Any] | None = None,
    experiment: dict[str, Any] | None = None,
    run_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge defaults → place → experiment → run overrides."""
    cfg = load_yaml(defaults_path or DEFAULT_CONFIG_PATH)
    for layer in (place_overrides, experiment, run_overrides):
        if layer:
            cfg = _deep_merge(cfg, layer)
    return cfg


def config_hash(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def model_manifest(config: dict[str, Any], models: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = models or load_models()
    roles = config.get("models", {})
    manifest: dict[str, Any] = {}
    for role, name in roles.items():
        entry = catalog.get(name)
        if entry is None:
            raise ConfigError(f"Unknown model role target '{name}' for role '{role}'")
        manifest[role] = {
            "name": name,
            "kind": entry.get("kind"),
            "model": entry.get("model"),
            "model_digest": entry.get("model_digest", "unknown"),
        }
    return manifest
