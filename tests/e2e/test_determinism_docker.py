"""Same recipe and seed give byte-identical output trees across worker counts and cached reruns."""

import hashlib
from pathlib import Path

import pytest

from glyphforge import run
from glyphforge.render import docker
from glyphforge.store import read_store

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

FORMULAS = [
    r"\upsilon+a",
    r"a+v",
    r"\omicron+a",
    r"a_{I}+b",
    r"a_{l}+b",
    r"f'(t)=g(t)",
    r"a'+b'",
    r"\overline{ab}+c",
    r"\mathbb{R}^{n}",
    r"\bar{a}+b",
]
FIXTURES = Path(__file__).parents[1] / "fixtures"
RECIPE = {
    "export": {
        "formats": ["glyphfix"],
        "blocklist": {"path": "blocklist.jsonl", "sha256": hashlib.sha256((FIXTURES / "blocklist.jsonl").read_bytes()).hexdigest()},
    },
    "seed": 11,
    "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": FORMULAS},
    "classes": ["greek.upsilon_v", "greek.omicron_o", "digits.I_l", "primes.prime_l", "decorations.bar_overline", "alphabets.drop_mathbb"],
    "styles": [{"name": "default", "font": "cm", "size": 12}, {"name": "libertine", "font": "libertine", "size": 12}],
}


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_byte_identical_across_workers_and_cache(tmp_path):
    a = run(RECIPE, tmp_path / "a", cache=tmp_path / "ca", max_parallel=1, batch_size=4, base_dir=FIXTURES)
    b = run(RECIPE, tmp_path / "b", cache=tmp_path / "cb", max_parallel=2, batch_size=4, base_dir=FIXTURES)
    c = run(RECIPE, tmp_path / "c", cache=tmp_path / "ca", max_parallel=2, batch_size=4, base_dir=FIXTURES)
    assert a.recipe_sha256 == b.recipe_sha256 == c.recipe_sha256
    assert a.rows_kept > 0
    tree = _tree(tmp_path / "a")
    assert "export/glyphfix/trainset.jsonl" in tree
    assert tree == _tree(tmp_path / "b") == _tree(tmp_path / "c")


def test_seed_is_recorded_and_changes_output(tmp_path):
    run(RECIPE, tmp_path / "s11", cache=tmp_path / "c", max_parallel=2, base_dir=FIXTURES)
    run({**RECIPE, "seed": 12}, tmp_path / "s12", cache=tmp_path / "c", max_parallel=2, base_dir=FIXTURES)
    r11, s11, _ = read_store(tmp_path / "s11")
    r12, s12, _ = read_store(tmp_path / "s12")
    assert r11["recipe_sha256"] != r12["recipe_sha256"] and r11["seed"] == 11 and r12["seed"] == 12
    assert {s["seed"] for s in s11}.isdisjoint({s["seed"] for s in s12})
