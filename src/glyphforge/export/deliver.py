"""The one export entry point: verify the pinned blocklist and run the leak gate first, then write into a temp dir and publish atomically."""

from __future__ import annotations

import hashlib
import io
import json
import zlib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import numpy as np
import PIL
from PIL import Image

from glyphforge.degrade import apply_ops, degrade_ops
from glyphforge.export.card import attribution_text, dataset_card
from glyphforge.export.glyphfix import control_glyphs_used, write_glyphfix
from glyphforge.export.leak import LeakError, leak_check, load_blocklist
from glyphforge.fileio import atomic_dir
from glyphforge.recipe import SCHEMA_VERSION, ExportSpec
from glyphforge.store import read_store

LEAK_POLICY = "Exact canon formula, source formula or paper id match against the pinned blocklist fails the export; no exemptions"


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _deliver(store_dir: Path, samples: list[dict], spec: ExportSpec, seed: int) -> Iterator[tuple[dict, bytes, list[dict]]]:
    """Yield (row, delivered PNG, ops) in sample_id order; pair rows share ops through their pair_id, undegraded bytes pass through."""
    for s in sorted(samples, key=lambda r: r["sample_id"]):
        ops = degrade_ops(spec.degrade, seed, s["pair_id"] or s["sample_id"])
        png = apply_ops((store_dir / s["image"]).read_bytes(), ops)
        if ops:
            sha = hashlib.sha256(png).hexdigest()
            with Image.open(io.BytesIO(png)) as im:
                width, height = im.size
            s = {**s, "image": f"images/{sha[:2]}/{sha}.png", "image_sha256": sha, "width": width, "height": height}
        yield s, png, ops


def export_store(
    store_dir: Path, out_dir: Path, fmt: Literal["glyphfix", "parquet"], *, spec: ExportSpec | None = None, base_dir: Path | None = None
) -> dict:
    if fmt not in ("glyphfix", "parquet"):
        raise ValueError(f"export format must be 'glyphfix' or 'parquet', got {fmt!r}")
    store_dir, out_dir = Path(store_dir), Path(out_dir)
    run, samples, _ = read_store(store_dir)
    if run.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"store predates schema {SCHEMA_VERSION} (no source_canon); re-run the recipe")
    frozen = ExportSpec.model_validate(run["recipe"]["export"])
    spec = spec or frozen
    if spec.blocklist is None:
        raise ValueError("export needs export.blocklist (path + sha256); the leak gate has no skip")
    hint = "" if base_dir else "; the store's blocklist path is relative to the recipe directory: pass --recipe <recipe file> or export from that directory"
    blocklist = load_blocklist(spec.blocklist, base_dir or Path.cwd(), hint=hint)
    if hits := leak_check(samples, blocklist):
        raise LeakError(hits)
    degrade = None if spec.degrade is None else spec.degrade.model_dump(mode="json")
    manifest = {
        "format": "glyphfix-trainset" if fmt == "glyphfix" else "hf-parquet", "n_rows": len(samples),
        "licenses": dict(sorted(Counter(s["licence"] for s in samples).items())), "roles": dict(sorted(Counter(s["role"] for s in samples).items())),
        "sources": dict(sorted(Counter(s["source"] for s in samples).items())), "recipe_sha256": run.get("recipe_sha256"),
        "generator_version": run.get("generator_version"), "image_digest": next(iter({s["image_digest"] for s in samples}), None),
        "export_spec": spec.model_dump(mode="json"), "export_spec_sha256": _sha(spec.model_dump(mode="json")), "export_spec_from_store": spec == frozen,
        "degrade": degrade, "degrade_sha256": None if degrade is None else _sha(degrade),
        "blocklist": {"path": spec.blocklist.path, "sha256": spec.blocklist.sha256, "formulas": len(blocklist.formulas), "papers": len(blocklist.papers)}, "leak_policy": LEAK_POLICY, "leak_hits": 0,
        "pillow_version": PIL.__version__, "numpy_version": np.__version__, "zlib_version": zlib.ZLIB_RUNTIME_VERSION,
    }  # fmt: skip
    with atomic_dir(out_dir) as tmp:
        delivered = _deliver(store_dir, samples, spec, run["seed"])
        if fmt == "glyphfix":
            rows = write_glyphfix(tmp, delivered)
            manifest |= {
                "groups": dict(sorted(Counter(r["group"] for r in rows).items())),
                "control_glyphs_used": control_glyphs_used(samples),
            }
        else:
            import pyarrow

            from glyphforge.export.parquet import parquet_row, write_parquet

            rows = (parquet_row(s, png, ops) for s, png, ops in delivered)
            shards = write_parquet(tmp, rows, shard_bytes=spec.shard_mb * 2**20, row_group_rows=spec.row_group_rows)
            manifest |= {"shards": shards, "pyarrow_version": pyarrow.__version__}
            (tmp / "README.md").write_text(dataset_card(run, manifest), encoding="utf-8")
        (tmp / "ATTRIBUTION.md").write_text(attribution_text(samples), encoding="utf-8")
        (tmp / "export_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def export_glyphfix(store_dir: Path, out_dir: Path, **kw) -> dict:
    return export_store(store_dir, out_dir, "glyphfix", **kw)


def export_parquet(store_dir: Path, out_dir: Path, **kw) -> dict:
    return export_store(store_dir, out_dir, "parquet", **kw)
