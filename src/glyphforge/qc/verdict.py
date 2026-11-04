"""Authoritative QC: compile gate, exact bitmap_sha256 ambiguity gate, diagnostic flags, pair integrity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from glyphforge.pixels import apply_policy
from glyphforge.render import RenderInfrastructureError, RenderResult, compare, load_bitmap

POLICIES = ("drop", "flag")
FLAGS = ("ambiguous", "identical-after-policy", "near-identical")


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str | None
    flags: tuple[str, ...] = ()
    alternates_not_rendered: int = 0


def _policy_image(result: RenderResult, cache: Path | None) -> tuple[tuple[int, int], bytes]:
    arr = load_bitmap(result, cache)
    if arr is None:
        raise RenderInfrastructureError("cached bitmap missing or unreadable for a rendered entry; delete the render cache entry and rerun")
    img = apply_policy(Image.fromarray(arr))
    return img.size, img.tobytes()


def verdict(gt: RenderResult, alts: Sequence[RenderResult], cache: Path | None, *, policy: str) -> Verdict:
    if policy not in POLICIES:
        raise ValueError(f"unknown ambiguity policy {policy!r}; expected one of {POLICIES}")
    n_bad = sum(a.status != "rendered" for a in alts)
    if gt.status != "rendered":
        return Verdict(False, gt.status, (), n_bad)
    rendered = [a for a in alts if a.status == "rendered"]
    same = [a for a in rendered if a.bitmap_sha256 == gt.bitmap_sha256]
    ambiguous = bool(same)
    flags: set[str] = set()
    gt_img = _policy_image(gt, cache) if rendered else None
    for a in (a for a in rendered if a not in same):
        if compare(gt, a, cache)[1]:
            flags.add("near-identical")
        if _policy_image(a, cache) == gt_img:
            flags.add("identical-after-policy")
    if ambiguous and policy == "drop":
        return Verdict(False, "ambiguous-identical", tuple(sorted(flags)), n_bad)
    if ambiguous:
        flags.add("ambiguous")
    return Verdict(True, None, tuple(sorted(flags)), n_bad)


def pair_integrity(target: Verdict, hard_negative: Verdict) -> tuple[Verdict, Verdict]:
    if target.keep == hard_negative.keep:
        return target, hard_negative
    gone = "pair_partner_dropped"
    return (replace(target, keep=False, reason=gone), hard_negative) if target.keep else (target, replace(hard_negative, keep=False, reason=gone))
