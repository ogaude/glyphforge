"""Shared fixtures: a fake render_many and a directory-tree reader."""

import hashlib
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
