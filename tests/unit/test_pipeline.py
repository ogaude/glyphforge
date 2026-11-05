import hashlib
import json
import re
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import glyphforge
from glyphforge import pipeline
from glyphforge.errors import ConfusionPair, builtin_registry
from glyphforge.pipeline import build_registry, resolve_classes, run
from glyphforge.recipe import Recipe
from glyphforge.store import LEDGER_KEYS, SAMPLE_KEYS, read_store

REG = builtin_registry()
VS = ["a_{v}+v", "b+v+c", "v-d", "e*v", "v+f", "2v+g", "h+v"]


def _recipe(formulas, classes, **kw):
    return {
        "seed": 3,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": formulas},
        "classes": classes,
        "styles": [{"name": "default", "font": "cm", "size": 12}, {"name": "lib", "font": "libertine", "size": 12}],
        "structure": {"kinds": {"display": 1.0}},
        "composition": {"total": 6},
        **kw,
    }



def _go(tmp_path, recipe, name="out", **kw):
    r = run(recipe, tmp_path / name, cache=tmp_path / f"c-{name}", **kw)
    return r, *read_store(tmp_path / name)


def _plugin(monkeypatch, tmp_path):
    mod = types.ModuleType("fail_plugin")
    mod.register_classes = lambda r: r.register(ConfusionPair("plug.fail_v", truth=r"\fail", confusable="v", family="plug"))
    monkeypatch.setitem(sys.modules, "fail_plugin", mod)
    return {"plugins": ["fail_plugin"]}


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


def test_exact_quotas_and_run_json(tmp_path, fake):
    names = ["greek.upsilon_v", "greek.nu_v", "greek.iota_i"]
    forms = [r"v+\nu+i+a", r"\upsilon+\iota+b+v", r"x+v+i+\nu", r"\nu+\upsilon+i+c"]
    recipe = _recipe(forms, names, composition={"total": 12, "shares": dict(zip(names, (0.5, 0.25, 0.25), strict=True))})
    r, run_info, samples, ledger = _go(tmp_path, recipe)
    assert r.slots_planned == 12 and r.rows_kept == len(samples) == 24 and r.rows_dropped == len(ledger) == 0
    assert Counter(s["error_class"] for s in samples if s["role"] == "target") == dict(zip(names, (6, 3, 3), strict=True))
    assert r.shortfall["short_total"] == 0 and r.shortfall["short_classes"] == [] and r.warnings == run_info["balance"]["warnings"]
    assert all(set(s) == set(SAMPLE_KEYS) for s in samples)
    assert run_info["quotas"] == dict(zip(names, (6, 3, 3), strict=True)) and run_info["shortfall"] == r.shortfall
    assert run_info["schema_version"] == 2 and run_info["attempts"] == {"cap": 5, "rounds": 1}
    assert run_info["counts"]["slots_planned"] == run_info["counts"]["slots_kept"] == 12
    assert run_info["token_estimator"] == {"fit": [0.92, 6.5], "cap": 440} and run_info["grammar_table_version"]
    assert run_info["mix_shares"] == [1.0] and run_info["sources"] == [{"kind": "list"}]
    assert set(run_info) >= {"scale", "balance", "survival", "styles", "render_config", "control_glyphs_used", "alternates_not_rendered"}
    assert len(fake) == 1 and fake[0][0] == "display" and len(set(fake[0][1])) == len(fake[0][1])
    for f in ("trainset.jsonl", "export_manifest.json"):
        assert (tmp_path / "out" / "glyphfix" / f).is_file()
    with_counter, *_ = _go(tmp_path, recipe, "counted", token_counter=len)
    counted_info, counted, _ = read_store(tmp_path / "counted")
    assert counted_info["token_estimator"] == {"custom": "len"} and with_counter.rows_kept > 0
    assert all(s["n_tokens"] == len(s["label"]) for s in counted)  # each row counts its own label, hard negatives included


def test_slot_style_is_shared_by_its_rows(tmp_path, fake):
    _, _, samples, _ = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"], composition={"total": 4, "hard_negative_ratio": 2}))
    by_slot = {}
    for s in samples:
        by_slot.setdefault(s["slot"], []).append(s)
    for rows in by_slot.values():
        extra = [x for x in rows if x["control_kind"] == "extra"]
        assert len(rows) == 3 and len(extra) == 1
        e, t = extra[0], next(x for x in rows if x["role"] == "target")
        assert (e["role"], e["pair_id"], e["sample_id"]) == ("hard_negative", None, f"{t['pair_id']}-c0")
        assert all(e[k] == t[k] for k in ("style", "font", "size_pt", "column_cm", "structure", "wrapper"))
        assert e["control_glyph"] and t["control_glyph"] is None
    assert Counter(s["control_kind"] for s in samples) == {"pair": 8, "extra": 4}


def test_failing_class_is_a_reported_shortfall(tmp_path, fake, monkeypatch):
    plug = _plugin(monkeypatch, tmp_path)
    names = ["greek.upsilon_v", "plug.fail_v"]
    r, run_info, samples, ledger = _go(tmp_path, _recipe(VS, names, composition={"total": 4}, **plug))
    assert Counter(s["error_class"] for s in samples if s["role"] == "target") == {"greek.upsilon_v": 2}
    assert r.shortfall["short_classes"] == ["plug.fail_v"] and r.shortfall["classes"]["plug.fail_v"] == {"target": 2, "achieved": 0, "short": 2}
    failed = [x for x in ledger if x["error_class"] == "plug.fail_v"]
    assert len(failed) == 2 * 2 * 5 and {x["attempt"] for x in failed} == set(range(5))
    assert {(x["role"], x["reason"]) for x in failed} == {("target", "compile-failed"), ("hard_negative", "pair_partner_dropped")}
    assert all(set(x) == set(LEDGER_KEYS) for x in ledger)
    assert [[run_info["classes"][1], f] for f in ("cm", "libertine")] == [z for z in r.survival["zero_yield"] if z[0] == run_info["classes"][1]]
    assert run_info["attempts"]["rounds"] == 5


def test_slot_is_the_unit_and_refills(tmp_path, fake):
    r, run_info, samples, ledger = _go(tmp_path, _recipe(["v+a", r"v+\fail"], ["greek.upsilon_v"], composition={"total": 6}))
    assert run_info["counts"]["slots_kept"] == 6 and len(samples) == 12 and ledger
    assert {x["reason"] for x in ledger} <= {"compile-failed", "pair_partner_dropped"}
    assert max(s["attempt"] for s in samples) > 0 and r.shortfall["short_total"] == 0


def test_failed_extra_control_ledgers_the_whole_slot(tmp_path, fake):
    recipe = _recipe(["v+a", r"v+\fail"], ["greek.upsilon_v"], composition={"total": 1, "hard_negative_ratio": 2})
    r, _, samples, ledger = _go(tmp_path, recipe)
    assert not samples and r.shortfall["short_total"] == 1
    assert {x["attempt"] for x in ledger} == set(range(5))
    assert {"compile-failed", "slot_partner_dropped"} <= {x["reason"] for x in ledger}
    assert len(ledger) == 3 * 5


def test_zero_formula_slots_are_counted(tmp_path, fake):
    r, run_info, samples, _ = _go(tmp_path, _recipe(["a+b"], ["greek.upsilon_v"]))
    assert r.rows_kept == 0 and not samples and run_info["counts"]["no_draw"] == 6 * 5
    assert ["greek.upsilon_v@1", "cm"] in r.survival["zero_yield"] and r.shortfall["short_total"] == 6 and not fake


@pytest.mark.parametrize("policy", ["drop", "flag"])
def test_ambiguity_policy(tmp_path, fake, policy):
    recipe = _recipe([r"\boldsymbol{x}+y"], ["decorations.boldsymbol_bm"], composition={"total": 2}, qc={"ambiguity": policy})
    r, _, samples, ledger = _go(tmp_path, recipe)
    if policy == "drop":
        assert r.rows_kept == 0 and len(ledger) == 2 * 2 * 5 and {x["reason"] for x in ledger} == {"ambiguous-identical"}
        assert len(r.survival["zero_yield"]) == 2
    else:
        assert len(samples) == 4 and all("ambiguous" in s["flags"] for s in samples)


def test_one_render_call_per_wrapper_and_round(tmp_path, fake):
    recipe = _recipe(VS, ["greek.upsilon_v"], structure={"kinds": {"display": 1, "inline": 1, "numbered": 1}}, composition={"total": 12})
    _, run_info, samples, _ = _go(tmp_path, recipe)
    per = Counter(w for w, _ in fake)
    assert set(per) == {"display", "line"} and all(n <= run_info["attempts"]["rounds"] for n in per.values())
    assert all(len(set(pairs)) == len(pairs) for _, pairs in fake)
    assert {s["wrapper"] for s in samples if s["structure"] == "display"} == {"display"}
    assert {s["wrapper"] for s in samples if s["structure"] != "display"} == {"line"}


def test_numbered_and_inline_labels(tmp_path, fake):
    _, _, samples, _ = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"], structure={"kinds": {"numbered": 1.0}}))
    assert samples and all(re.search(r"\n\\tag\{\d+\}$", s["label"]) and s["wrapper"] == "line" for s in samples)
    _, _, samples, _ = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"], structure={"kinds": {"inline": 1.0}}), "inline")
    assert samples and all("$" in s["label"] and s["wrapper"] == "line" for s in samples)


def test_invisible_tag_is_dropped_as_ambiguous(tmp_path, invisible_tag):
    r, _, samples, ledger = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"], structure={"kinds": {"numbered": 1.0}}))
    assert not samples and r.rows_kept == 0 and {x["reason"] for x in ledger} == {"ambiguous-identical"}


def test_pad_px_pads_after_qc(tmp_path, fake):
    base = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"]), "p0")[2]
    padded = _go(tmp_path, _recipe(VS, ["greek.upsilon_v"], render={"pad_px": 4}), "p4")[2]
    assert [(s["slot"], s["role"], s["label"]) for s in base] == [(s["slot"], s["role"], s["label"]) for s in padded]
    for a, b in zip(base, padded, strict=True):
        assert (a["pad_px"], b["pad_px"]) == (0, 4) and a["bitmap_sha256"] == b["bitmap_sha256"]
        assert (b["width"], b["height"]) == (a["width"] + 8, a["height"] + 8)
        with Image.open(tmp_path / "p4" / b["image"]) as im:
            assert im.size == (b["width"], b["height"])
            assert np.asarray(im)[:4].min() == 255


def test_source_mix_exact_and_synthetic_attribution(tmp_path, fake):
    parts = [{"kind": "grammar"}, {"kind": "inline", "licence": "CC-BY-4.0", "formulas": [{"latex": f, "paper_id": "2101.0001", "paper_version": "v1", "authors": ["Ada L"]} for f in VS]}]
    recipe = _recipe(VS, ["greek.upsilon_v"], composition={"total": 10})
    recipe["source"] = {"kind": "mix", "parts": parts, "shares": [0.3, 0.7]}
    r, run_info, samples, _ = _go(tmp_path, recipe)
    targets = [s for s in samples if s["role"] == "target"]
    assert r.shortfall["short_total"] == 0 and Counter(s["source"] for s in targets) == {"grammar": 3, "list": 7}
    assert run_info["mix_shares"] == [0.3, 0.7]
    for s in targets:
        if s["source"] == "grammar":
            assert s["licence"] == "CC0-1.0" and s["authors"] == [] and s["paper_id"].startswith("synth:" + r.recipe_sha256[:8])
        else:
            assert (s["licence"], s["paper_id"], s["paper_version"], s["authors"]) == ("CC-BY-4.0", "2101.0001", "v1", ["Ada L"])


def test_mutation_rows_carry_snapshot_attribution(tmp_path, fake):
    rows = [
        {"authors": [f"Ada {i}"], "env": "equation*", "latex": latex, "licence": "CC-BY-4.0", "paper_id": f"2101.000{i}", "paper_version": "v1", "split": split}
        for i, (latex, split) in enumerate([("a_{v}+b", "train"), ("v+c", "train"), ("d+v", "train"), ("w+v", "val")])
    ]
    snap = tmp_path / "s.jsonl"
    snap.write_text("".join(json.dumps(x) + "\n" for x in rows), "utf-8")
    meta = {"reference_crops": {"width_q": {"p50": 100}, "height_q": {"p50": 40}, "area_below_floor": 0.5}}
    snap.with_suffix(".meta.json").write_text(json.dumps(meta), "utf-8")
    recipe = _recipe([], ["greek.upsilon_v"])
    recipe["source"] = {"kind": "mutation", "path": "s.jsonl", "sha256": hashlib.sha256(snap.read_bytes()).hexdigest()}
    r, run_info, samples, _ = _go(tmp_path, recipe, base_dir=tmp_path)
    assert samples and r.shortfall["short_total"] == 0
    for s in samples:
        assert s["source"] == "mutation" and s["licence"] == "CC-BY-4.0" and s["paper_version"] == "v1"
        assert s["paper_id"].startswith("2101.000") and s["authors"] and s["paper_id"] != "2101.0003"
    assert run_info["sources"] == [{"kind": "mutation", "sha256": recipe["source"]["sha256"], "rejected": {"split": 1}}]
    assert run_info["scale"]["references"]["corpus"] == meta["reference_crops"]
    assert run_info["corpus_meta_sha256"] == hashlib.sha256(snap.with_suffix(".meta.json").read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(run_info)


def test_omicron_uses_lgrmath_style_and_font_cells(tmp_path, fake):
    r, run_info, _, _ = _go(tmp_path, _recipe([r"\omicron+a"], ["greek.omicron_o"], composition={"total": 2}))
    styles = [s for _, pairs in fake for _, s in pairs]
    assert {s.is_default for s in styles} == {False} and all("lgrmath" in s.preamble for s in styles)
    assert set(r.survival["cells"]) == {"greek.omicron_o@1|cm", "greek.omicron_o@1|libertine"} and run_info["styles"]["lib"]["preamble_sha256"]


def test_byte_identical_across_workers_batches_and_no_paths(tmp_path, fake, tree):
    recipe = _recipe(VS + ["f'(t)=g(t)"], ["greek.upsilon_v", "primes.prime_l"], composition={"total": 10, "hard_negative_ratio": 1.5})
    run(recipe, tmp_path / "a", cache=tmp_path / "ca", max_parallel=1, batch_size=2)
    run(recipe, tmp_path / "b", cache=tmp_path / "cb", max_parallel=3, batch_size=100)
    ta, tb = tree(tmp_path / "a"), tree(tmp_path / "b")
    assert ta == tb and ta
    for blob in ta.values():
        assert str(tmp_path).encode() not in blob and str(Path.home()).encode() not in blob


def test_existing_run_refused_before_render(tmp_path, fake):
    out = tmp_path / "out"
    out.mkdir()
    (out / "run.json").write_text("{}")
    with pytest.raises(FileExistsError):
        run(_recipe(VS, ["greek.upsilon_v"]), out, cache=tmp_path / "c")
    assert not fake


def test_run_accepts_yaml_path(tmp_path, fake):
    p = tmp_path / "r.yaml"
    p.write_text(json.dumps(_recipe(VS, ["greek.upsilon_v"])))
    assert run(p, tmp_path / "out", cache=tmp_path / "c").rows_kept == 12


def test_lazy_top_level_api():
    assert glyphforge.run is pipeline.run
    from glyphforge import errors

    assert glyphforge.register is errors.register
    with pytest.raises(AttributeError):
        glyphforge.does_not_exist  # noqa: B018
    assert glyphforge.__all__ == sorted(glyphforge.__all__) and "__version__" in glyphforge.__all__
    code = "import sys, glyphforge; assert not {'pydantic','yaml','numpy'} & set(sys.modules); glyphforge.run"
    subprocess.run([sys.executable, "-I", "-c", code], check=True)
