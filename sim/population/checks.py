from __future__ import annotations

from collections import Counter
from typing import Any

from sim.db.models import Agent


def run_population_checks(agents: list[Agent]) -> dict[str, Any]:
    """Lightweight §16.7-style checks for synthetic MVP populations."""
    n = len(agents)
    if n == 0:
        return {"pass": False, "error": "empty population"}

    ages = [int(a.demographics.get("age", 0)) for a in agents]
    sexes = Counter(str(a.demographics.get("sex", "?")) for a in agents)
    age_ok = min(ages) >= 0 and max(ages) <= 100
    sex_share = {k: v / n for k, v in sexes.items()}
    sex_ok = all(0.2 <= s <= 0.8 for s in sex_share.values()) if len(sex_share) >= 2 else True

    consistent = 0
    for a in agents:
        anchors = a.anchors or []
        age = a.demographics.get("age")
        occ = a.demographics.get("occupation")
        ok = bool(a.narrative) and bool(anchors)
        if age is not None:
            ok = ok and any(str(age) in anch for anch in anchors)
        if occ:
            ok = ok and (occ in a.narrative or any(str(occ) in anch for anch in anchors))
        if ok:
            consistent += 1
    consistency_rate = consistent / n

    # Attitude variance proxy from traits
    openness = [float(a.traits.get("openness", 0.5)) for a in agents]
    mean_o = sum(openness) / n
    var_o = sum((x - mean_o) ** 2 for x in openness) / n
    variance_ok = var_o >= 0.01

    checks = {
        "demographics": {
            "pass": age_ok and sex_ok,
            "n": n,
            "sex_share": sex_share,
            "age_min": min(ages),
            "age_max": max(ages),
        },
        "persona_consistency": {
            "pass": consistency_rate >= 0.95,
            "rate": consistency_rate,
            "target": 0.95,
        },
        "attitude_variance": {"pass": variance_ok, "openness_var": var_o},
        "narrative_plausibility": {
            "pass": all(bool(a.narrative) for a in agents),
            "empty": sum(1 for a in agents if not a.narrative),
        },
    }
    checks["pass"] = all(v.get("pass", False) for v in checks.values() if isinstance(v, dict))
    return checks
