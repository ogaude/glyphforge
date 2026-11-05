"""Mutation input: freeze glyphfix-math training rows into the generic contract (D-01), then load them pinned by sha256 (D-02) behind the split/licence gate (SRC-03)."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from glyphforge.sources.base import LICENSES, Formula
from glyphforge.sources.listing import _draw_index, _resolve_inside
from glyphforge.store import _atomic_write, _jsonl

if TYPE_CHECKING:
    from glyphforge.errors.api import ErrorClass
    from glyphforge.recipe.schema import SourceSpec

CONTRACT_KEYS = ("authors", "env", "latex", "licence", "paper_id", "paper_version", "split")
ENV_MAP = {"displaymath": "equation*", "equation": "equation*", "align": "align*", "gather": "gather*"}
# (pool, shard dir, builder_version, shard split, catalog files glob, catalog split)
POOLS = (
    ("v1", "data/corpus/shards/records", "1", "train", "data/catalog/train_dev.jsonl", "train"),
    ("v11", "data/corpus_v11/shards/records", "2", "train_extra", "data/corpus_v11/catalog/batch-*.jsonl", "train_extra"),
)
_NUMBERING = re.compile(r"\\(?:label|tag|nonumber)(?![A-Za-z])")
_MIN_AREA = 65_536  # Qwen2-VL smart_resize minimum pixels
_MIB = 1 << 20


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_MIB):
            h.update(chunk)
    return h.hexdigest()


def _quantiles(values: list[int]) -> dict[str, int]:
    v = sorted(values)
    return {f"p{q}": v[max(0, -(-q * len(v) // 100) - 1)] for q in (1, 10, 50, 90, 99)} if v else {}


def _jsonl_rows(path: Path):
    return (json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip())


def build_snapshot(glyphfix_root: Path, out: Path) -> dict:
    """Write the sorted contract JSONL to ``out`` and its ``.meta.json`` sidecar; return the meta."""
    root, out = Path(glyphfix_root), Path(out)
    meta_path = out.with_suffix(".meta.json")
    if out.exists() or meta_path.exists():
        raise FileExistsError(f"{out} already exists")
    rows, widths, heights, digests, pools = [], [], [], [], {}
    for pool, shard_dir, builder, shard_split, cat_glob, cat_split in POOLS:
        catalog = {}
        for cat in sorted(root.glob(cat_glob)):
            if cat.name.endswith(".excluded.jsonl"):
                continue
            digests.append(f"{cat.relative_to(root)}:{_file_sha256(cat)}")
            catalog.update({r["arxiv_id"]: r for r in _jsonl_rows(cat)})
        read, rejected, papers = 0, Counter(), set()
        kept = []
        for shard in sorted((root / shard_dir).glob("*.jsonl")):
            digests.append(f"{shard.relative_to(root)}:{_file_sha256(shard)}")
            for r in _jsonl_rows(shard):
                read += 1
                if r.get("builder_version") != builder:
                    raise ValueError(f"{shard}: builder_version {r.get('builder_version')!r}, expected {builder!r}")
                paper = catalog.get(r["arxiv_id"])
                if r["split"] != shard_split:
                    rejected["split"] += 1
                elif paper is None:
                    rejected["no_catalog"] += 1
                elif paper.get("quarantined"):
                    rejected["quarantined"] += 1
                elif paper["split"] != cat_split:
                    rejected["split"] += 1
                elif r["env"] not in ENV_MAP:
                    rejected["env"] += 1
                elif _NUMBERING.search(r["latex"]):
                    rejected["numbering"] += 1
                else:
                    row = {
                        "authors": list(paper["authors"]),
                        "env": ENV_MAP[r["env"]],
                        "latex": r["latex"],
                        "licence": r["license_spdx"],
                        "paper_id": r["arxiv_id"],
                        "paper_version": r["paper_version"],
                    }
                    try:
                        Formula(**row)
                    except ValidationError:
                        rejected["invalid_formula"] += 1
                        continue
                    kept.append(row | {"split": "train"})
                    widths.append(r["width"])
                    heights.append(r["height"])
                    papers.add(r["arxiv_id"])
        rows += kept
        pools[pool] = {
            "builder_version": builder,
            "papers": len(papers),
            "read": read,
            "rejected": dict(rejected),
            "rows": len(kept),
        }
    rows.sort(key=lambda r: (r["paper_id"], r["latex"], r["env"]))
    data = _jsonl(rows)
    below = sum(w * h < _MIN_AREA for w, h in zip(widths, heights, strict=True))
    meta = {
        "papers": sum(p["papers"] for p in pools.values()),
        "pools": pools,
        "reference_crops": {
            "area_below_floor": below / len(widths) if widths else 0.0,
            "height_q": _quantiles(heights),
            "width_q": _quantiles(widths),
        },
        "rejected": dict(sum((Counter(p["rejected"]) for p in pools.values()), Counter())),
        "rows": len(rows),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sources_sha256": hashlib.sha256("\n".join(sorted(digests)).encode()).hexdigest(),
    }
    _atomic_write(out, data)
    _atomic_write(meta_path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    return meta


@dataclass(frozen=True)
class MutationSource:
    """Gated snapshot rows; a Formula is built (and so validated) only when a row is drawn."""

    rows: tuple[dict, ...]
    sha256: str
    rejected: dict[str, int]
    _index: dict = field(default_factory=dict, compare=False, repr=False)

    def draw(self, cls: ErrorClass, rng: random.Random, *, level: str | None = None, multiline: bool = False) -> Formula | None:
        """A formula with at least one site of ``cls`` carrying its own licence and attribution, or None."""
        i = _draw_index([r["latex"] for r in self.rows], cls, rng, self._index)
        if i is None:
            return None
        try:
            return Formula(**self.rows[i])
        except ValidationError:
            return None


def load_snapshot(spec: SourceSpec, base_dir: Path) -> MutationSource:
    """Verify the pinned sha256, then keep only licence-allowed train rows without duplicate latex."""
    path = _resolve_inside(base_dir, spec.path, ".jsonl")
    if (actual := _file_sha256(path)) != spec.sha256:
        raise ValueError(f"snapshot sha256 mismatch: recipe pins {spec.sha256}, file is {actual}")
    rows, seen, rejected = [], set(), Counter()
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if tuple(sorted(row)) != CONTRACT_KEYS:
                    raise ValueError(f"expected keys {CONTRACT_KEYS}, got {tuple(sorted(row))}")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{spec.path}:{lineno}: {exc}") from exc
            if row.pop("split") != "train":
                rejected["split"] += 1
            elif row["licence"] not in LICENSES:
                rejected["licence"] += 1
            elif row["latex"] in seen:
                rejected["duplicate"] += 1
            else:
                seen.add(row["latex"])
                rows.append(row)
    return MutationSource(tuple(rows), spec.sha256, dict(rejected))
