"""Per-slot RNGs seeded from sha256(seed:stage:slot:attempt); only Random.random() is cross-version stable."""

from __future__ import annotations

import hashlib
import random


def slot_seed(seed: int, stage: str, slot: int, attempt: int = 0) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{stage}:{slot}:{attempt}".encode()).digest()[:8], "big")


def slot_rng(seed: int, stage: str, slot: int, attempt: int = 0) -> random.Random:
    """Callers must only use ``.random()``: choice/shuffle/sample change across Python versions."""
    return random.Random(slot_seed(seed, stage, slot, attempt))
