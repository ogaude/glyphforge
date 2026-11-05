"""Internal store: content-addressed PNG crops, samples.jsonl, ledger.jsonl and run.json (written last)."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from PIL import Image

SAMPLE_KEYS = (
    "attempt", "authors", "bitmap_sha256", "class_version", "column_cm", "control_glyph", "control_kind", "env", "error_class", "family",
    "flags", "font", "generator_version", "height", "image", "image_digest", "image_sha256", "label", "licence", "n_sites", "n_tokens",
    "pad_px", "pair_id", "paper_id", "paper_version", "recipe_sha256", "role", "rules", "sample_id", "seed", "site_level", "size_pt",
    "slot", "source", "structure", "style", "style_preamble_sha256", "width", "wrapper",
)  # fmt: skip
LEDGER_KEYS = (
    "attempt", "control_kind", "error_class", "font", "label", "pair_id", "reason", "role", "sample_id", "slot", "source", "structure", "style",
)  # fmt: skip
_SHA = re.compile(r"^[0-9a-f]{64}$")
JOURNAL = ".journal"


def png_bytes(arr: np.ndarray) -> bytes:
    img = Image.fromarray(arr)
    if img.mode != "L":
        raise ValueError(f"expected a uint8 2-D grayscale crop, got mode {img.mode}")
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _check_keys(row: dict, keys: tuple[str, ...], what: str) -> None:
    if set(row) != set(keys):
        raise ValueError(f"{what} keys differ: missing {sorted(set(keys) - set(row))}, extra {sorted(set(row) - set(keys))}")


def _jsonl(rows: Sequence[dict]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def write_store(out_dir: Path, samples: Sequence[dict], images: Mapping[str, bytes], ledger: Sequence[dict], run: dict) -> None:
    out_dir = Path(out_dir)
    if (out_dir / "run.json").exists():
        raise FileExistsError(f"{out_dir / 'run.json'} already exists")
    for s in samples:
        _check_keys(s, SAMPLE_KEYS, "sample")
    for row in ledger:
        _check_keys(row, LEDGER_KEYS, "ledger row")
    for sha, data in images.items():
        if not _SHA.match(sha) or hashlib.sha256(data).hexdigest() != sha:
            raise ValueError(f"image name {sha!r} is not the sha256 of its bytes")
    for s in samples:
        sha = s["image_sha256"]
        if sha not in images or s["image"] != f"images/{sha[:2]}/{sha}.png":
            raise ValueError(f"sample {s['sample_id']!r} image path does not match images/<sha[:2]>/<sha>.png of a stored image")
    for sha, data in images.items():
        _atomic_write(out_dir / "images" / sha[:2] / f"{sha}.png", data)
    _atomic_write(out_dir / "samples.jsonl", _jsonl(sorted(samples, key=lambda r: (r["slot"], r["role"], r["sample_id"]))))
    _atomic_write(out_dir / "ledger.jsonl", _jsonl(sorted(ledger, key=lambda r: (r["slot"], r["attempt"], r["role"], r["sample_id"]))))
    _atomic_write(out_dir / "run.json", (json.dumps(run, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def read_store(out_dir: Path) -> tuple[dict, list[dict], list[dict]]:
    out_dir = Path(out_dir)
    if not (out_dir / "run.json").is_file():
        raise FileNotFoundError("incomplete store: run.json missing")
    rows = lambda name: [json.loads(line) for line in (out_dir / name).read_text(encoding="utf-8").splitlines()]
    return json.loads((out_dir / "run.json").read_text(encoding="utf-8")), rows("samples.jsonl"), rows("ledger.jsonl")


def write_round(
    out_dir: Path, header: dict, round_no: int, kept: Mapping[int, list[dict]], ledger: Sequence[dict], images: Mapping[str, bytes],
    entries: Sequence[tuple], no_draw: int, not_rendered: int,
) -> None:
    """Journal one finished round: images first, then the round file as the commit marker."""
    root = Path(out_dir) / JOURNAL
    for sha, data in images.items():
        if not (path := root / "images" / f"{sha}.png").exists():
            _atomic_write(path, data)
    body = {"header": header, "round": round_no, "kept": {str(i): r for i, r in kept.items()}, "ledger": list(ledger),
            "entries": [list(e) for e in entries], "no_draw": no_draw, "not_rendered": not_rendered}  # fmt: skip
    _atomic_write(root / f"round-{round_no:03d}.json", json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def read_journal(out_dir: Path, header: dict) -> list[dict]:
    """Committed rounds in order, with images loaded and entries as tuples; foreign or damaged journals raise ValueError."""
    root, rounds = Path(out_dir) / JOURNAL, []
    for path in sorted(root.glob("round-[0-9][0-9][0-9].json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        if body["header"] != header:
            raise ValueError(f"journal belongs to a different recipe: {path} header differs from this run")
        body["kept"] = {int(i): r for i, r in body["kept"].items()}
        body["entries"] = [(*e[:3], tuple(e[3])) for e in body["entries"]]
        body["images"] = {}
        for row in [r for rows in body["kept"].values() for r in rows]:
            sha = row["image_sha256"]
            data = (root / "images" / f"{sha}.png").read_bytes() if (root / "images" / f"{sha}.png").is_file() else b""
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError(f"journal image {sha} is missing or does not match its name")
            body["images"][sha] = data
        rounds.append(body)
    if [b["round"] for b in rounds] != list(range(len(rounds))):
        raise ValueError("journal rounds are not consecutive")
    return rounds
