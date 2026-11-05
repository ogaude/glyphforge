"""Leak scan: freeze a benchmark blocklist from glyphfix-math, load it pinned by sha256, and apply one exact hit rule to export rows and draws."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from glyphforge.canon import canonical
from glyphforge.fileio import atomic_write, file_sha256, jsonl_bytes
from glyphforge.sources.listing import resolve_inside

if TYPE_CHECKING:
    from glyphforge.recipe.schema import BlocklistPin

BENCHMARK = "data/benchmark/records.jsonl"
# (set name, shard dir, split values kept; None keeps every row)
SHARD_SETS = (
    ("benchmark_shards", "data/benchmark/shards/records", None),
    ("dev", "data/corpus/shards/records", {"dev"}),
    ("fresh_benchmark", "data/corpus_v11/shards/records", {"fresh_benchmark"}),
    ("page_set", "data/corpus_v11/shards/records", {"page_set"}),
)
ID_FILES = ("data/splits/benchmark_ids.txt", "data/splits/quarantine_ids.txt")
ASSIGNMENTS = ("data/corpus_v11/split/assignment.tsv", "data/corpus_v11/split_refresh1/assignment.tsv")
HELD_OUT = {"fresh_benchmark", "page_set"}


def base_id(paper_id: str) -> str:
    return re.sub(r"v\d+$", "", paper_id)


@dataclass(frozen=True)
class Blocklist:
    formulas: frozenset[str]
    papers: frozenset[str]
    sha256: str

    def hits(self, label: str, source_canon: str | None, paper_id: str | None) -> list[tuple[str, str]]:
        """Every reason a row collides: exact canonical label, exact canonical source formula, or a blocklisted base paper."""
        canon = canonical(label)
        base = base_id(paper_id) if paper_id else None
        checks = (("formula", canon, self.formulas), ("source", source_canon, self.formulas), ("paper", base, self.papers))
        return [(reason, v) for reason, v, pool in checks if v is not None and v in pool]

    def match(self, label: str, source_canon: str | None, paper_id: str | None) -> tuple[str, str] | None:
        return next(iter(self.hits(label, source_canon, paper_id)), None)


class LeakError(Exception):
    def __init__(self, hits: list[dict]) -> None:
        super().__init__(f"leak gate: {len(hits)} blocklist hit(s); nothing was exported")
        self.hits = hits


def _jsonl_rows(path: Path):
    return (json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip())


def build_blocklist(glyphfix_root: Path, out: Path) -> dict:
    """Write the sorted blocklist JSONL to ``out`` and its ``.meta.json`` sidecar; return the meta."""
    root, out = Path(glyphfix_root), Path(out)
    meta_path = out.with_suffix(".meta.json")
    if out.exists() or meta_path.exists():
        raise FileExistsError(f"{out} already exists")
    digests, formulas, papers, paper_files = [], set(), set(), {}
    sets: dict[str, int] = {}

    def read(path: Path) -> Path:
        digests.append(f"{path.relative_to(root)}:{file_sha256(path)}")
        return path

    def take(name: str, rows) -> None:
        for r in rows:
            formulas.add(canonical(r["latex"]))
            papers.add(base_id(r["arxiv_id"]))
            sets[name] = sets.get(name, 0) + 1

    take("benchmark_records", _jsonl_rows(read(root / BENCHMARK)))
    for name, shard_dir, keep in SHARD_SETS:
        sets.setdefault(name, 0)
        for shard in sorted((root / shard_dir).glob("*.jsonl")):
            take(name, (r for r in _jsonl_rows(read(shard)) if keep is None or r["split"] in keep))
    for rel in ID_FILES:
        ids = {base_id(s) for s in read(root / rel).read_text("utf-8").split() if s}
        paper_files[rel] = len(ids)
        papers |= ids
    for rel in ASSIGNMENTS:
        if not (path := root / rel).is_file():
            continue  # split_refresh1 only exists in newer checkouts
        with read(path).open(encoding="utf-8", newline="") as fh:
            ids = {base_id(r["id"]) for r in csv.DictReader(fh, delimiter="\t") if r["v11_split"] in HELD_OUT}
        paper_files[rel] = len(ids)
        papers |= ids
    data = jsonl_bytes([{"k": "formula", "v": v} for v in sorted(formulas)] + [{"k": "paper", "v": v} for v in sorted(papers)])
    meta = {
        "counts": {"formulas": len(formulas), "papers": len(papers)},
        "format": "glyphforge-blocklist",
        "paper_files": paper_files,
        "sets": sets,
        "sha256": hashlib.sha256(data).hexdigest(),
        "sources_sha256": hashlib.sha256("\n".join(sorted(digests)).encode()).hexdigest(),
        "version": 1,
    }
    atomic_write(out, data)
    atomic_write(meta_path, (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode())
    return meta


def load_blocklist(pin: BlocklistPin, base_dir: Path, *, hint: str = "") -> Blocklist:
    """Verify the pinned sha256, then parse the strict {"k","v"} lines; a pool with no entries is refused. ``hint`` is appended to a not-found error."""
    path = resolve_inside(base_dir, pin.path, ".jsonl")
    if not path.is_file():
        raise FileNotFoundError(f"blocklist not found: {path} (recipe pins sha256 {pin.sha256}){hint}")
    if (actual := file_sha256(path)) != pin.sha256:
        raise ValueError(f"blocklist sha256 mismatch: {path}: recipe pins {pin.sha256}, file is {actual}")
    pools: dict[str, set[str]] = {"formula": set(), "paper": set()}
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or set(row) != {"k", "v"} or row["k"] not in pools or not isinstance(row["v"], str) or not row["v"]:
                    raise ValueError('expected {"k": "formula"|"paper", "v": non-empty str}')
            except ValueError as exc:
                raise ValueError(f"{pin.path}:{lineno}: {exc}") from exc
            pools[row["k"]].add(base_id(row["v"]) if row["k"] == "paper" else row["v"])
    for kind, pool in pools.items():
        if not pool:
            raise ValueError(f"blocklist {path} has 0 {kind}s; the leak gate would be vacuous")
    return Blocklist(frozenset(pools["formula"]), frozenset(pools["paper"]), actual)


def leak_check(samples: Iterable[dict], blocklist: Blocklist) -> list[dict]:
    """One record per (sample, reason) hit, in sample order."""
    return [
        {"sample_id": s["sample_id"], "pair_id": s["pair_id"], "reason": reason, "entry": entry}
        for s in samples
        for reason, entry in blocklist.hits(s["label"], s.get("source_canon"), s.get("paper_id"))
    ]
