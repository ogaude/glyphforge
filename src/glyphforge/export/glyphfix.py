"""Export a store to glyphfix-math's training-set layout: trainset.jsonl + root-relative PNGs + export_manifest.json."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from glyphforge.sources.base import LICENSES
from glyphforge.store import read_store

FENCE = "`" * 3
ROLE_GROUP = {"target": "error", "hard_negative": "control"}
_COPIED = ("authors", "class_version", "error_class", "family", "flags", "generator_version", "pair_id", "paper_version", "recipe_sha256", "seed", "style")


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


def _dump(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def export_glyphfix(store_dir: Path, out_dir: Path) -> dict:
    store_dir, out_dir = Path(store_dir), Path(out_dir)
    run, samples, _ = read_store(store_dir)
    if (out_dir / "trainset.jsonl").exists():
        raise FileExistsError(f"{out_dir / 'trainset.jsonl'} already exists")
    rows = [_row(s) for s in samples]
    for s in samples:
        dest = out_dir / s["image"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(store_dir / s["image"], dest)
    manifest = {
        "format": "glyphfix-trainset",
        "n_rows": len(rows),
        "groups": dict(sorted(Counter(r["group"] for r in rows).items())),
        "control_glyphs_used": control_glyphs_used(samples),
        "licenses": dict(sorted(Counter(r["license_spdx"] for r in rows).items())),
        "recipe_sha256": run.get("recipe_sha256"),
    }
    _dump(out_dir / "trainset.jsonl", "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows))
    _dump(out_dir / "export_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
