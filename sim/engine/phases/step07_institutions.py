from __future__ import annotations

from sim.engine.context import RunContext
from sim.institutions.agents import institution_respond, media_baseline_story


def run(ctx: RunContext, sweep: int) -> None:
    institution_respond(ctx, sweep)
    media_baseline_story(ctx, sweep)
    ctx.session.flush()
