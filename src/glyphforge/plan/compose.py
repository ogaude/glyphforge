"""Multi-site minimal pairs from single-site error classes (D-06)."""

from __future__ import annotations

import random
from collections.abc import Sequence

from glyphforge.errors.api import ErrorClass, Site, Variant


def choose_sites(sites: Sequence[Site], max_sites: int, rng: random.Random) -> tuple[Site, ...]:
    """1..max_sites pairwise non-overlapping sites, sorted by start descending; consumes only ``rng.random()``."""
    k, left = 1 + int(rng.random() * min(max_sites, len(sites))), list(sites)
    chosen: list[Site] = []
    while left and len(chosen) < k:
        s = left[int(rng.random() * len(left))]
        chosen.append(s)
        left = [o for o in left if o.end <= s.start or s.end <= o.start]
    return tuple(sorted(chosen, key=lambda s: s.start, reverse=True))


def _apply_all(latex: str, cls: ErrorClass, sites: Sequence[Site], base: int, flip: int | None, side: str) -> str:
    """Apply every site right to left (earlier offsets stay valid), taking ``side`` everywhere except site ``flip``, which takes the other.

    Site ``i`` always gets a fresh ``Random(base + i)``, so a plugin that draws from ``rng`` makes the same choice at a site in every pass.
    """
    other = "hard_negative" if side == "target" else "target"
    for i, site in enumerate(sites):
        latex = getattr(cls.apply(latex, site, random.Random(base + i)), other if i == flip else side)
    return latex


def compose(latex: str, cls: ErrorClass, sites: Sequence[Site], rng: random.Random) -> Variant:
    """Variant over several sites, with every single-site flip as an alternate so one invisible site cannot hide in a pair.

    ``sites`` must come from ``choose_sites`` (descending). A single site yields ``cls.apply`` with ``rng`` itself. Several sites draw one
    base seed from ``rng`` and give each site its own rng, identical across the target, hard-negative and flip passes. A plugin class whose
    single-site variant already carries extra misreads yields that variant for the leftmost site only.
    """
    if len(sites) == 1:
        return cls.apply(latex, sites[0], rng)
    base = int(rng.random() * 2**53)
    v0 = cls.apply(latex, sites[-1], random.Random(base + len(sites) - 1))
    if v0.target_alternates or v0.hard_negative_alternates:
        return v0
    target, hard_negative = (_apply_all(latex, cls, sites, base, None, side) for side in ("target", "hard_negative"))
    return Variant(
        target,
        hard_negative,
        v0.control_glyph,
        tuple(dict.fromkeys((hard_negative, *(_apply_all(latex, cls, sites, base, i, "target") for i in range(len(sites)))))),
        tuple(dict.fromkeys((target, *(_apply_all(latex, cls, sites, base, i, "hard_negative") for i in range(len(sites)))))),
        (("n_sites", str(len(sites))),),
    )
