import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import glyphforge
from glyphforge import pipeline
from glyphforge.errors import ConfusionPair, builtin_registry
from glyphforge.pipeline import build_registry, plan_candidates, resolve_classes, run
from glyphforge.recipe import DEFAULT_STYLES, Recipe, to_style
from glyphforge.render import RenderResult, cache_key
from glyphforge.render.cache import _cache_put
from glyphforge.rng import slot_seed
from glyphforge.sources.base import Formula
from glyphforge.store import LEDGER_KEYS, SAMPLE_KEYS, read_store

REG = builtin_registry()
H = "h" * 64


def _f(latex):
    return Formula(latex=latex, licence="CC0-1.0")


def _recipe(formulas, classes, **kw):
    return {
        "seed": 3,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": formulas},
        "classes": classes,
        "styles": [{"name": "default", "font": "cm", "size": 12}, {"name": "lib", "font": "libertine", "size": 12}],
        **kw,
    }


@pytest.fixture
def fake(monkeypatch):
    """Stand-in for render_many: bitmap derived from the latex (with \\bm folded into \\boldsymbol) and the style."""
    calls = []

    def render(latex_list, *, style=None, cache=None, max_parallel=None, batch_size=100):
        calls.append(list(zip(latex_list, style, strict=True)))
        out = []
        for latex, s in zip(latex_list, style, strict=True):
            key = cache_key(latex, style=s)
            if "\\fail" in latex:
                res = RenderResult(key, "compile-failed", None, None, "!")
                _cache_put(cache, res)
            else:
                digest = hashlib.sha256((latex.replace("\\bm", "\\boldsymbol") + s.preamble_sha256).encode()).digest()
                arr = np.tile(np.frombuffer(digest, dtype=np.uint8).reshape(4, 8), (4, 4))
                res = RenderResult(key, "rendered", arr.shape, hashlib.sha256(arr.tobytes()).hexdigest())
                _cache_put(cache, res, arr)
            out.append(res)
        return out

    monkeypatch.setattr(pipeline, "render_many", render)
    return calls


def test_build_registry_routes(tmp_path, monkeypatch):
    assert len(build_registry(Recipe()).names()) >= 45
    (tmp_path / "my_mod.py").write_text(
        "from glyphforge.errors import ConfusionPair\n"
        "def register_classes(reg):\n    reg.register(ConfusionPair('my.a_b', truth='a', confusable='b', family='my'))\n"
    )
    monkeypatch.syspath_prepend(tmp_path)
    reg = build_registry(Recipe(plugins=("my_mod",)))
    assert "my.a_b" in reg.names() and reg.modules[-1] == "my_mod"
    seen = []
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kw: seen.append(kw) or [])
    build_registry(Recipe())
    assert not seen
    build_registry(Recipe(entry_points=True))
    assert seen


def test_resolve_classes():
    assert resolve_classes(REG, None) == tuple(REG.get(n) for n in REG.names())
    assert [c.name for c in resolve_classes(REG, ["greek.upsilon_v", "greek.omicron_o"])] == ["greek.upsilon_v", "greek.omicron_o"]
    with pytest.raises(ValueError, match="did you mean"):
        resolve_classes(REG, ["greek.upsilon_vv"])
    with pytest.raises(ValueError, match="duplicate"):
        resolve_classes(REG, ["greek.upsilon_v"] * 2)


def test_plan_candidates_order_seed_and_sites():
    ups = REG.get("greek.upsilon_v")
    args = ([_f("a_{v}+v"), _f(r"\upsilon+a")], [ups], DEFAULT_STYLES)
    cands = plan_candidates(*args, seed=3, recipe_hash=H)
    assert cands == plan_candidates(*args, seed=3, recipe_hash=H)
    assert len(cands) == 3 * len(DEFAULT_STYLES)
    for i, c in enumerate(cands):
        assert c.slot == i
        assert c.pair_id == hashlib.sha256(f"{H}:{i}".encode()).hexdigest()[:16]
        assert c.seed == slot_seed(3, "variant", i)
    assert [c.style_name for c in cands[:3]] == [s.name for s in DEFAULT_STYLES]
    assert cands[0].variant.hard_negative == "a_{v}+v"
    assert cands[0].variant.target == r"a_{\upsilon}+v"
    assert cands[3].variant.target == r"a_{v}+\upsilon"
    assert cands[0].target_alternates == ("a_{v}+v",) and cands[0].hard_negative_alternates == (r"a_{\upsilon}+v",)


def test_class_packages_union_into_style():
    cands = plan_candidates([_f(r"\omicron+a")], [REG.get("greek.omicron_o"), REG.get("greek.upsilon_v")], DEFAULT_STYLES, seed=0, recipe_hash=H)
    omicron = [c for c in cands if c.error_class.name == "greek.omicron_o"]
    assert len(omicron) == len(DEFAULT_STYLES)
    for c, spec in zip(omicron, DEFAULT_STYLES, strict=True):
        assert c.style == to_style(spec, {"lgrmath"}) and c.style_name == spec.name


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_run_outputs_and_single_render_call(tmp_path, fake):
    r = run(_recipe(["a_{v}+v", r"\upsilon+a"], ["greek.upsilon_v"]), tmp_path / "out", cache=tmp_path / "c")
    assert len(fake) == 1
    assert len(set(fake[0])) == len(fake[0])
    run_info, samples, ledger = read_store(tmp_path / "out")
    assert r.pairs == 6 and r.rows_kept == len(samples) == 12 and r.rows_dropped == 0 == len(ledger)
    assert all(set(s) == set(SAMPLE_KEYS) for s in samples)
    by_pair = {}
    for s in samples:
        by_pair.setdefault(s["pair_id"], []).append(s)
    for pair in by_pair.values():
        t, h = sorted(pair, key=lambda s: s["role"], reverse=True)
        assert (t["role"], h["role"]) == ("target", "hard_negative") and t["style"] == h["style"]
        assert t["label"] != h["label"] and h["control_glyph"] and t["control_glyph"] is None
    first = samples[1]
    assert first["role"] == "target" and first["label"] == r"a_{\upsilon}+v" and samples[0]["label"] == "a_{v}+v"
    assert first["recipe_sha256"] == r.recipe_sha256 == run_info["recipe_sha256"]
    for f in ("trainset.jsonl", "export_manifest.json"):
        assert (tmp_path / "out" / "glyphfix" / f).is_file()
    assert set(run_info) >= {
        "schema_version", "generator_version", "seed", "recipe", "recipe_sha256", "classes", "plugins", "entry_points", "styles",
        "canon_versions", "render_config", "pixel_policy_version", "numpy_version", "pillow_version", "counts", "alternates_not_rendered",
        "survival", "control_glyphs_used",
    }
    assert run_info["classes"] == ["greek.upsilon_v@1"] and run_info["styles"]["lib"]["preamble_sha256"]
    assert run_info["control_glyphs_used"] == {"v": 6}


def test_run_omicron_uses_lgrmath_style_and_recipe_style_key(tmp_path, fake):
    run(_recipe([r"\omicron+a"], ["greek.omicron_o"]), tmp_path / "out", cache=tmp_path / "c")
    assert {s.is_default for _, s in fake[0]} == {False}
    assert all("lgrmath" in s.preamble for _, s in fake[0])
    run_info = read_store(tmp_path / "out")[0]
    assert set(run_info["survival"]["cells"]) == {"greek.omicron_o@1|default", "greek.omicron_o@1|lib"}


@pytest.mark.parametrize("policy", ["drop", "flag"])
def test_ambiguity_policy(tmp_path, fake, policy):
    recipe = _recipe([r"\boldsymbol{x}+y"], ["decorations.boldsymbol_bm"], qc={"ambiguity": policy})
    r = run(recipe, tmp_path / "out", cache=tmp_path / "c")
    _, samples, ledger = read_store(tmp_path / "out")
    if policy == "drop":
        assert r.rows_kept == 0 and len(ledger) == 4 and {x["reason"] for x in ledger} == {"ambiguous-identical"}
        assert all(set(x) == set(LEDGER_KEYS) for x in ledger)
        assert len(r.survival["zero_yield"]) == 2
    else:
        assert len(samples) == 4 and all("ambiguous" in s["flags"] for s in samples)


def test_failed_target_drops_partner(tmp_path, fake, monkeypatch):
    mod = types.ModuleType("fail_plugin")
    mod.register_classes = lambda r: r.register(ConfusionPair("plug.fail_v", truth=r"\fail", confusable="v", family="plug"))
    monkeypatch.setitem(sys.modules, "fail_plugin", mod)
    r = run(_recipe(["a+v"], ["plug.fail_v"], plugins=["fail_plugin"]), tmp_path / "out", cache=tmp_path / "c")
    run_info, samples, ledger = read_store(tmp_path / "out")
    assert not samples and r.rows_kept == 0
    assert {(x["role"], x["reason"]) for x in ledger} == {("target", "compile-failed"), ("hard_negative", "pair_partner_dropped")}
    assert run_info["plugins"] == ["fail_plugin"]


def test_class_without_sites_is_zero_yield(tmp_path, fake):
    r = run(_recipe(["a+b"], ["greek.upsilon_v"]), tmp_path / "out", cache=tmp_path / "c")
    assert r.pairs == 0 and r.survival["cells"]["greek.upsilon_v@1|default"]["planned"] == 0
    assert ["greek.upsilon_v@1", "default"] in r.survival["zero_yield"]


def test_byte_identical_across_workers_and_no_paths(tmp_path, fake):
    recipe = _recipe(["a_{v}+v", r"f'(t)=g(t)"], ["greek.upsilon_v", "primes.l"] if "primes.l" in REG.names() else ["greek.upsilon_v"])
    run(recipe, tmp_path / "a", cache=tmp_path / "ca", max_parallel=1)
    run(recipe, tmp_path / "b", cache=tmp_path / "cb", max_parallel=3)
    ta, tb = _tree(tmp_path / "a"), _tree(tmp_path / "b")
    assert ta == tb and ta
    for blob in ta.values():
        assert str(tmp_path).encode() not in blob and str(Path.home()).encode() not in blob


def test_existing_run_refused_before_render(tmp_path, fake):
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.json").write_text("{}")
    with pytest.raises(FileExistsError):
        run(_recipe(["a+v"], ["greek.upsilon_v"]), out, cache=tmp_path / "c")
    assert not fake


def test_run_accepts_yaml_path(tmp_path, fake):
    p = tmp_path / "r.yaml"
    p.write_text(json.dumps(_recipe(["a+v"], ["greek.upsilon_v"])))
    assert run(p, tmp_path / "out", cache=tmp_path / "c").pairs == 2


def test_lazy_top_level_api():
    assert glyphforge.run is pipeline.run
    from glyphforge import errors

    assert glyphforge.register is errors.register
    with pytest.raises(AttributeError):
        glyphforge.does_not_exist  # noqa: B018
    assert glyphforge.__all__ == sorted(glyphforge.__all__) and "__version__" in glyphforge.__all__
    code = "import sys, glyphforge; assert not {'pydantic','yaml','numpy'} & set(sys.modules); glyphforge.run"
    subprocess.run([sys.executable, "-I", "-c", code], check=True)
