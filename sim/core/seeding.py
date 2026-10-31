from __future__ import annotations

import hashlib
from typing import Any

import numpy as np


def derive_seed(master_seed: int, channel: str, sweep: int, *keys: Any) -> int:
    """Derive a deterministic 64-bit seed for one random decision.

    seed(run, channel, sweep, *keys) = int.from_bytes(
        sha256(f"{master_seed}|{channel}|{sweep}|{'|'.join(keys)}").digest()[:8], "big")
    """
    parts = [str(master_seed), str(channel), str(sweep), *[str(k) for k in keys]]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def rng_for(master_seed: int, channel: str, sweep: int, *keys: Any) -> np.random.Generator:
    """Create a PCG64 generator for exactly one seeded decision."""
    return np.random.Generator(np.random.PCG64(derive_seed(master_seed, channel, sweep, *keys)))
