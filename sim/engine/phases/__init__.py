from sim.engine.phases import step01_rules, step02_events, step03_deliver
from sim.engine.phases import step04_system1, step05_system2, step06_resolve
from sim.engine.phases import step07_institutions, step08_reflect, step09_metrics

PHASES = [
    step01_rules.run,
    step02_events.run,
    step03_deliver.run,
    step04_system1.run,
    step05_system2.run,
    step06_resolve.run,
    step07_institutions.run,
    step08_reflect.run,
    step09_metrics.run,
]

__all__ = ["PHASES"]
