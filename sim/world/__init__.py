"""World model package. Prefer submodule imports."""

__all__ = [
    "phone_ban_daily_impact",
    "check_delta",
    "commit_delta",
    "resolve_collisions",
]


def __getattr__(name: str):
    if name in ("check_delta", "commit_delta"):
        from sim.world import deltas

        return getattr(deltas, name)
    if name == "resolve_collisions":
        from sim.world.resolver import resolve_collisions

        return resolve_collisions
    if name == "phone_ban_daily_impact":
        from sim.world.rules import phone_ban_daily_impact

        return phone_ban_daily_impact
    raise AttributeError(name)
