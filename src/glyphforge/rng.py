"""Per-slot RNGs seeded from sha256(seed:stage:slot:attempt); only Random.random() is cross-version stable."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence


def slot_seed(seed: int, stage: str, slot: int | str, attempt: int = 0) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{stage}:{slot}:{attempt}".encode()).digest()[:8], "big")


def slot_rng(seed: int, stage: str, slot: int | str, attempt: int = 0) -> random.Random:
    """Callers must only use ``.random()``: choice/shuffle/sample change across Python versions."""
    return random.Random(slot_seed(seed, stage, slot, attempt))


def pick[T](rng: random.Random, items: Sequence[T], weights: Sequence[float]) -> T:
    """Weighted choice consuming exactly one ``rng.random()`` call."""
    if len(items) != len(weights) or not items or min(weights) < 0 or sum(weights) <= 0:
        raise ValueError("pick needs equal-length non-empty items/weights, non-negative with a positive sum")
    target, acc = rng.random() * sum(weights), 0.0
    for item, w in zip(items, weights, strict=True):
        acc += w
        if w > 0 and target < acc:
            return item
    return next(item for item, w in reversed(list(zip(items, weights, strict=True))) if w > 0)
