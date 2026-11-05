"""Row shape and writer for glyphfix-math's training-set layout: trainset.jsonl + root-relative PNGs (called by export_store)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from glyphforge.fileio import jsonl_bytes
from glyphforge.sources.base import LICENSES

FENCE = "`" * 3
ROLE_GROUP = {"target": "error", "hard_negative": "control"}
_COPIED = (
    "authors", "class_version", "control_kind", "error_class", "family", "flags", "generator_version", "pair_id", "paper_version",
    "recipe_sha256", "seed", "source", "structure", "style",
)  # fmt: skip


def target_text(latex: str) -> str:
    return FENCE + "latex\n" + latex + "\n" + FENCE


def control_glyphs_used(samples: Iterable[dict]) -> dict[str, int]:
    return dict(sorted(Counter(s["control_glyph"] for s in samples if s["role"] == "hard_negative").items()))


def _row(s: dict) -> dict:
    group = ROLE_GROUP[s["role"]]
    row = {k: s[k] for k in _COPIED}
    row.update(
        id=s["sample_id"], paper_id=s["paper_id"] or f"glyphforge/{s['recipe_sha256'][:8]}", image=s["image"], latex=s["label"],
        target_text=target_text(s["label"]), group=group, width=s["width"], height=s["height"], license_spdx=s["licence"],
        license_uri=LICENSES[s["licence"]],
    )
    row.update({"mining_class": s["error_class"]} if group == "error" else {"control_glyph": s["control_glyph"]})
    return row


def write_glyphfix(tmp: Path, delivered: Iterable[tuple[dict, bytes, list[dict]]]) -> list[dict]:
    """Write each delivered image at its row path plus ``trainset.jsonl``; returns the trainset rows."""
    rows = []
    for s, png, ops in delivered:
        dest = tmp / s["image"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(png)
        rows.append(_row(s) | {"degrade_ops": ops})
    (tmp / "trainset.jsonl").write_bytes(jsonl_bytes(rows))
    return rows
