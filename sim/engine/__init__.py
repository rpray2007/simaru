"""Sweep engine package. Import from submodules to avoid circular imports."""

__all__ = ["RunContext", "run_experiment"]


def __getattr__(name: str):
    if name in __all__:
        from sim.engine.sweep import RunContext, run_experiment

        return {"RunContext": RunContext, "run_experiment": run_experiment}[name]
    raise AttributeError(name)
