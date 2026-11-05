"""Shared fixtures: a fake render_many and a directory-tree reader."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from glyphforge import pipeline
from glyphforge.render import RenderResult, cache_key
from glyphforge.render.cache import _cache_put

STRIP_TAG = re.compile(r"\n\\tag\{\d+\}$")


def _install(monkeypatch, strip_tag):
    calls = []

    def render(latex_list, *, style=None, cache=None, max_parallel=None, batch_size=100, wrapper="display"):
        calls.append((wrapper, list(zip(latex_list, style, strict=True))))
        out = []
        for latex, s in zip(latex_list, style, strict=True):
            key = cache_key(latex, wrapper=wrapper, style=s)
            if "\\fail" in latex:
                res = RenderResult(key, "compile-failed", None, None, "!")
                _cache_put(cache, res)
            else:
                shown = STRIP_TAG.sub("", latex) if strip_tag else latex
                digest = hashlib.sha256((wrapper + shown.replace("\\bm", "\\boldsymbol") + s.preamble_sha256).encode()).digest()
                arr = np.tile(np.frombuffer(digest, dtype=np.uint8).reshape(4, 8), (4, 4))
                res = RenderResult(key, "rendered", arr.shape, hashlib.sha256(arr.tobytes()).hexdigest())
                _cache_put(cache, res, arr)
            out.append(res)
        return out

    monkeypatch.setattr(pipeline, "render_many", render)
    return calls


@pytest.fixture
def fake(monkeypatch):
    """Stand-in for render_many: bitmap derived from wrapper, latex (with \\bm folded into \\boldsymbol) and style."""
    return _install(monkeypatch, False)


@pytest.fixture
def invisible_tag(monkeypatch):
    return _install(monkeypatch, True)


@pytest.fixture
def tree():
    return lambda root: {str(p.relative_to(Path(root))): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def _sample(slot, role, label, cls, glyph, licence, arr, extra=False):
    from glyphforge import store

    png = store.png_bytes(arr)
    sha = hashlib.sha256(png).hexdigest()
    by = licence.startswith("CC-BY")
    row = dict.fromkeys(store.SAMPLE_KEYS)
    row.update(
        authors=["A. Author"] if by else [], bitmap_sha256="b" * 64, class_version="1", env="equation*", error_class=cls, family=cls.split(".")[0],
        flags=[], generator_version="0.1.0", height=arr.shape[0], image=f"images/{sha[:2]}/{sha}.png", image_digest="sha256:x", image_sha256=sha,
        label=label, licence=licence, pair_id=f"p{slot}", paper_id="2101.00001" if by else None, paper_version="v1" if by else None,
        recipe_sha256="ab" * 32, role=role, rules={}, sample_id=f"s{slot}-{role}", seed=slot, slot=slot, style="default",
        style_preamble_sha256="s" * 64, width=arr.shape[1], source_canon="src",
        control_glyph=glyph if role == "hard_negative" else None, attempt=0, column_cm=None, control_kind="extra" if extra else "pair", font="cm",
        n_sites=1, n_tokens=3, pad_px=0, site_level="base", size_pt=12, source="list", structure="display", wrapper="display",
    )  # fmt: skip
    if extra:
        row.update(pair_id=None, sample_id=f"p{slot}-c0")
    return row, {sha: png}


@pytest.fixture
def make_store(tmp_path):
    """Build a five-row store (a CC0 pair, a CC-BY pair, an unpaired control) with a pinned blocklist; returns a namespace."""
    from types import SimpleNamespace

    from glyphforge import store
    from glyphforge.recipe import ExportSpec

    def build(*, blocklist=(), schema_version=3, **spec):
        a, b = np.full((8, 12), 255, np.uint8), np.full((9, 14), 255, np.uint8)
        a[3:5, 3:9] = 0
        b[2:7, 4:10] = 0
        parts = [
            _sample(0, "target", r"\upsilon", "greek.upsilon_v@1", None, "CC0-1.0", a),
            _sample(0, "hard_negative", "v", "greek.upsilon_v@1", "v", "CC0-1.0", b),
            _sample(1, "target", r"\bar{x}", "decorations.bar_overline@1", None, "CC-BY-4.0", a),
            _sample(1, "hard_negative", r"\overline{x}", "decorations.bar_overline@1", r"\overline", "CC-BY-4.0", b),
            _sample(0, "hard_negative", "w", "greek.upsilon_v@1", "v", "CC0-1.0", b, extra=True),
        ]
        samples = [p[0] for p in parts]
        images = {k: v for _, im in parts for k, v in im.items()}
        ledger = [{k: s[k] for k in store.LEDGER_KEYS if k != "reason"} | {"reason": None} for s in samples]
        bl = tmp_path / "bl.jsonl"
        bl.write_text("".join(json.dumps(r) + "\n" for r in [{"k": "paper", "v": "9999.99999"}, *blocklist]), "utf-8")
        pin = {"path": "bl.jsonl", "sha256": hashlib.sha256(bl.read_bytes()).hexdigest()}
        export = {"formats": ["glyphfix", "parquet"], "blocklist": pin, **spec}
        run = {
            "schema_version": schema_version, "seed": 7, "recipe": {"export": export}, "recipe_sha256": "ab" * 32, "generator_version": "0.1.0",
            "canon_versions": {"canon": 1}, "render_config": {"dpi": 300}, "pixel_policy_version": 1,
        }  # fmt: skip
        root = tmp_path / "store"
        store.write_store(root, samples, images, ledger, run)
        return SimpleNamespace(store=root, samples=samples, images=images, spec=ExportSpec.model_validate(export), base_dir=tmp_path)

    return build
