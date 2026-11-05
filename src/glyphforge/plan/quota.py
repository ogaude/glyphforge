"""Exact integer allocation, Bresenham spreading, synthetic paper buckets and the shortfall table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from math import floor

SYNTH_BUCKET_ROWS = 30


def largest_remainder(total: int, shares: Mapping[str, float]) -> dict[str, int]:
    """Integers summing to ``total``, proportional to ``shares``; remainder ties go to the earlier key."""
    fr = {k: Fraction(str(v)) for k, v in shares.items()}
    norm = sum(fr.values())
    exact = {k: total * v / norm for k, v in fr.items()}
    out = {k: floor(v) for k, v in exact.items()}
    for k in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True)[: total - sum(out.values())]:  # stable: ties keep mapping order
        out[k] += 1
    return out


def spread(i: int, rate: float) -> int:
    """Count for slot ``i`` so that prefix sums equal ``floor(n * rate)`` exactly."""
    q = Fraction(str(rate))
    return floor((i + 1) * q) - floor(i * q)


def class_slots(quotas: Mapping[str, int]) -> list[str]:
    """Class label per slot, round-robin in mapping order until every quota is spent."""
    left, out = dict(quotas), []
    while any(left.values()):
        for k in quotas:
            if left[k]:
                out.append(k)
                left[k] -= 1
    return out


def synthetic_paper_ids(row_counts: Sequence[int], prefix: str, bucket_rows: int = SYNTH_BUCKET_ROWS) -> list[str]:
    """Greedy bucket id per slot; a slot never splits across buckets and an oversize slot gets its own."""
    ids, bucket, used = [], 0, 0
    for n in row_counts:
        if used and used + n > bucket_rows:
            bucket, used = bucket + 1, 0
        ids.append(f"{prefix}:{bucket}")
        used += n
    return ids


def shortfall(quotas: Mapping[str, int], achieved: Mapping[str, int]) -> dict:
    classes = {k: {"target": quotas[k], "achieved": achieved.get(k, 0), "short": max(0, quotas[k] - achieved.get(k, 0))} for k in sorted(quotas)}
    return {
        "classes": classes,
        "short_total": sum(c["short"] for c in classes.values()),
        "short_classes": [k for k, c in classes.items() if c["short"]],
    }
