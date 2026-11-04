"""Content-addressed render cache: key formula and on-disk layout match glyphfix-math for the default style."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from glyphforge import paths
from glyphforge.canon import safety
from glyphforge.render import docker, raster
from glyphforge.render.style import Style

STATUSES = ("rendered", "compile-failed", "blank-page", "rejected", "overflow", "timeout", "empty")


def render_config() -> dict:
    return {
        "image": docker.IMAGE,
        "preamble_sha256": docker.PREAMBLE_SHA256,
        "wrap_version": safety.WRAP_VERSION,
        "filter_version": safety.FILTER_VERSION,
        "dpi": raster.RENDER_DPI,
        "ink_threshold": raster.INK_THRESHOLD,
        "tolerance": {
            "version": raster.TOLERANCE_VERSION,
            "shape_px": raster.TOL_SHAPE_PX,
            "pixel_delta": raster.TOL_PIXEL_DELTA,
            "max_component_px": raster.TOL_MAX_COMPONENT_PX,
            "max_diff_px": raster.TOL_MAX_DIFF_PX,
        },
    }


@dataclass
class RenderResult:
    key: str
    status: str
    shape: tuple[int, int] | None
    bitmap_sha256: str | None
    note: str = ""


def cache_key(latex: str, *, wrapper: str = "display", style: Style | None = None) -> str:
    payload = docker.IMAGE_DIGEST + "\n" + docker.PREAMBLE_SHA256 + "\n" + safety.WRAP_VERSION + "\n" + safety.FILTER_VERSION + "\n" + str(raster.RENDER_DPI) + "\n" + latex
    if wrapper != "display":
        payload += "\nwrapper=" + wrapper
    if style is not None and not style.is_default:
        payload += "\nstyle=" + style.preamble_sha256
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_root(cache: Path | None) -> Path:
    return (Path(cache) if cache is not None else paths.cache_dir()) / "render"


def _entry(cache: Path | None, key: str, suffix: str) -> Path:
    return _cache_root(cache) / key[:2] / f"{key}{suffix}"


def _cache_get(cache: Path | None, key: str) -> RenderResult | None:
    p = _entry(cache, key, ".json")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        status = d.get("status")
        # entries poisoned by pre-fix code (infrastructure failures cached as LaTeX failures) are re-rendered
        if status == "timeout" or (status == "compile-failed" and not str(d.get("note", "")).startswith("!")):
            return None
        # a "rendered" entry whose bitmap was lost is a miss (re-render), not a silent non-match
        if status == "rendered" and not _entry(cache, key, ".npy").is_file():
            return None
        shape = tuple(d["shape"]) if d.get("shape") else None
        return RenderResult(key, d["status"], shape, d.get("bitmap_sha256"), d.get("note", ""))
    except (KeyError, AttributeError, TypeError, ValueError):
        return None


def _cache_put(cache: Path | None, res: RenderResult, bitmap: np.ndarray | None = None) -> None:
    jp = _entry(cache, res.key, ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": res.status, "shape": list(res.shape) if res.shape else None, "bitmap_sha256": res.bitmap_sha256, "note": res.note}
    for final, mode, enc, write in (
        (_entry(cache, res.key, ".npy"), "wb", None, None if bitmap is None else lambda fh: np.save(fh, bitmap)),
        (jp, "w", "utf-8", lambda fh: fh.write(json.dumps(payload))),  # json last: a partial write is a cache miss
    ):
        if write is None:
            continue
        fd, tmp = tempfile.mkstemp(dir=jp.parent, prefix=f".{res.key}.", suffix=f"{final.suffix}.tmp")
        try:
            with os.fdopen(fd, mode, encoding=enc) as fh:
                write(fh)
            os.replace(tmp, final)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise


def load_bitmap(result: RenderResult, cache: Path | None = None) -> np.ndarray | None:
    if result.status != "rendered":
        return None
    try:
        return np.load(_entry(cache, result.key, ".npy"))
    except (OSError, ValueError, EOFError):
        return None


def compare(a: RenderResult, b: RenderResult, cache: Path | None = None) -> tuple[bool, bool]:
    if a.status != "rendered" or b.status != "rendered":
        return False, False
    ba, bb = load_bitmap(a, cache), load_bitmap(b, cache)
    if ba is None or bb is None:
        # a rendered entry whose bitmap is unreadable must not score as "not identical"
        raise docker.RenderInfrastructureError("cached bitmap missing or unreadable for a rendered entry; delete the render cache entry and rerun")
    return raster.compare_arrays(ba, bb)
