from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

PROMPTS_DIR = Path(__file__).parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)

TEMPLATE_FOR_ROLE = {
    "system2": "system2_v1.jinja",
    "circle": "circle_v1.jinja",
    "world_master": "world_master_v1.jinja",
    "world_master_resolve": "world_master_v1.jinja",
    "world_master_judgment": "world_master_v1.jinja",
    "world_master_realize": "world_master_v1.jinja",
    "institution": "institution_v1.jinja",
    "reflection": "reflection_v1.jinja",
    "narrative": "narrative_v1.jinja",
}


def render_prompt(role: str, context: dict[str, Any]) -> str | None:
    name = TEMPLATE_FOR_ROLE.get(role)
    if not name:
        return None
    return _ENV.get_template(name).render(**context)


def template_version(role: str) -> str:
    name = TEMPLATE_FOR_ROLE.get(role, "none")
    return name.replace(".jinja", "")
