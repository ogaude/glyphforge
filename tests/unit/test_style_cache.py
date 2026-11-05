import hashlib
import json
import pathlib

import numpy as np
import pytest

from glyphforge.canon import safety
from glyphforge.render import cache, docker
from glyphforge.render.style import Style

GOLDEN = pathlib.Path(__file__).parent.parent / "fixtures" / "render_golden.jsonl"
DEFAULT_KEY = "5c4f6d7a41407bbe425fcf52188599432f8bc89dba4770fb167576600d1640cc"  # FILTER_VERSION 4
# glyphfix-math key (filter 2); diverges until the CR-01..03 fix lands upstream
GM_DEFAULT_KEY = "313423b35e9130aa86d42a8ee5488095070843cc3cde7e6b0f938a674aaf7c24"


def test_compare_requires_rendered(tmp_path):
    a = cache.RenderResult("k1", "compile-failed", None, None)
    b = cache.RenderResult("k2", "rendered", (1, 1), "x")
    assert cache.compare(a, b, cache=tmp_path) == (False, False)


def test_compare_unreadable_bitmap_is_infrastructure(tmp_path):
    a = cache.RenderResult("k1", "rendered", (1, 1), "x")
    with pytest.raises(docker.RenderInfrastructureError):
        cache.compare(a, a, cache=tmp_path)


def test_cache_put_get_roundtrip(tmp_path):
    res = cache.RenderResult("ab" + "0" * 62, "rendered", (2, 3), "h")
    cache._cache_put(tmp_path, res, np.zeros((2, 3), dtype=np.uint8))
    assert cache._cache_get(tmp_path, res.key) == res
    assert cache.load_bitmap(res, tmp_path).shape == (2, 3)


def test_config_and_hash():
    raw = (pathlib.Path(docker.__file__).parent / "preamble.tex").read_bytes()
    assert docker.PREAMBLE_SHA256 == hashlib.sha256(raw).hexdigest()
    c = cache.render_config()
    assert set(c) == {"image", "preamble_sha256", "wrap_version", "filter_version", "dpi", "ink_threshold", "tolerance"}
    assert c["preamble_sha256"] == docker.PREAMBLE_SHA256
    assert c["filter_version"] == safety.FILTER_VERSION == "4"
    assert c["wrap_version"] == "1" and c["dpi"] == 300 and c["image"] == docker.IMAGE
    assert set(c["tolerance"]) == {"version", "shape_px", "pixel_delta", "max_component_px", "max_diff_px"}
    assert "upgreek" in raw.decode() and r"\begin{document}" not in raw.decode()


def test_cache_key_stability(monkeypatch):
    k = cache.cache_key("x+1")
    assert k == DEFAULT_KEY == cache.cache_key("x+1")
    assert k != cache.cache_key("x+2")
    for mod, name, value in [
        (safety, "WRAP_VERSION", "2"),
        (docker, "PREAMBLE_SHA256", "0" * 64),
        (safety, "FILTER_VERSION", "5"),
        (docker, "IMAGE_DIGEST", "sha256:" + "0" * 64),
    ]:
        monkeypatch.setattr(mod, name, value)
        assert cache.cache_key("x+1") != k, name
        monkeypatch.undo()


def test_image_is_digest_pinned():
    assert "@sha256:" in docker.IMAGE and ":latest" not in docker.IMAGE
    assert docker.IMAGE.endswith(docker.IMAGE_DIGEST)


def test_style_keys():
    newtx = Style(font="newtx")
    assert cache.cache_key("x+1", style=Style()) == DEFAULT_KEY
    assert cache.cache_key("x+1", style=newtx) != DEFAULT_KEY
    assert cache.cache_key("x+1", style=newtx) != cache.cache_key("x+1", style=Style(size=10))
    payload = (
        docker.IMAGE_DIGEST + "\n" + docker.PREAMBLE_SHA256 + "\n" + safety.WRAP_VERSION + "\n" + safety.FILTER_VERSION
        + "\n300\nx+1\nstyle=" + newtx.preamble_sha256
    )
    assert cache.cache_key("x+1", style=newtx) == hashlib.sha256(payload.encode()).hexdigest()


def test_default_key_matches_glyphfix_math_golden_rows(monkeypatch):
    """The key formula is still byte-identical to glyphfix-math (D-02); only the FILTER_VERSION input differs."""
    lines = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
    meta = next(r for r in lines if "_meta" in r)["_meta"]
    rows = [r for r in lines if "_meta" not in r]
    assert rows
    monkeypatch.setattr(safety, "FILTER_VERSION", meta["filter_version"])
    for r in rows:
        assert cache.cache_key(r["latex"]) == r["cache_key"]
    assert cache.cache_key("x+1") == GM_DEFAULT_KEY


def test_column_preamble():
    """One consistent geometry line carries the column (CR-01) and hyphenation is off (WR-02); no column keeps the margin geometry."""
    pre = Style(size=10, column_cm=8.5).preamble
    assert pre.count("geometry") == 1
    assert "left=1cm,top=1cm,textwidth=8.5cm,textheight=17cm]{geometry}" in pre and "margin=1cm" not in pre
    assert "\\hyphenpenalty=10000 \\exhyphenpenalty=10000\n" in pre
    assert "hyphenpenalty" not in Style(size=10).preamble and "margin=1cm" in Style(size=10).preamble
    assert not Style(column_cm=12).is_default
    with pytest.raises(ValueError):
        Style(column_cm=0)


def test_style_preambles():
    assert Style().preamble == docker.PREAMBLE
    assert Style().preamble_sha256 == docker.PREAMBLE_SHA256
    assert Style(size=8).preamble.startswith("\\documentclass[8pt]{extarticle}")
    assert Style(size=10).preamble.startswith("\\documentclass[10pt]{article}")
    stix = Style(font="stix2").preamble
    assert "mathrsfs" not in stix and "amssymb" not in stix and "upgreek" not in stix
    assert "\\usepackage{extra}" in Style(extra=("\\usepackage{extra}",)).preamble
    assert not Style(font="newtx").is_default


def test_style_validation():
    with pytest.raises(ValueError):
        Style(font="nope")
    with pytest.raises(ValueError):
        Style(size=13)


def test_cache_paths(tmp_path, monkeypatch):
    assert cache._entry(tmp_path, "abcd", ".json") == tmp_path / "render" / "ab" / "abcd.json"
    monkeypatch.setenv("GLYPHFORGE_CACHE", str(tmp_path))
    assert cache._cache_root(None) == tmp_path / "render"
