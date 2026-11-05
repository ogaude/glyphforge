"""End-to-end runs through the digest-pinned sandbox: families, exact gate, flags, ledger, zero-yield, export load, user classes."""

import socket
from pathlib import Path

import pytest

from glyphforge import pipeline
from glyphforge.errors import Registry, check_error_class, pairs_from_alignment
from glyphforge.pipeline import resolve_classes, run
from glyphforge.plan import build_context, draw_slot
from glyphforge.recipe import DEFAULT_STYLES, Recipe, StyleSpec, frozen_recipe, recipe_sha256, to_style
from glyphforge.render import Style, docker, render_many
from glyphforge.store import read_store

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

FAMILIES = ("primes", "greek", "digits", "decorations", "alphabets")
FONTS = tuple(sorted({s.font for s in DEFAULT_STYLES}))


def _inline(formulas, classes, **kw):
    return {
        "seed": 5,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": formulas},
        "classes": classes,
        "styles": [{"name": "default", "font": "cm", "size": 12}],
        **kw,
    }


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    base = tmp_path_factory.mktemp("default_run")
    result = run({}, base / "out", cache=base / "cache", max_parallel=2)
    return (base / "out", *read_store(base / "out"), result)


def test_every_family_end_to_end(default_run):
    _, run_json, samples, _, _ = default_run
    for fam in FAMILIES:
        kept = [s for s in samples if s["family"] == fam]
        assert {s["role"] for s in kept} == {"target", "hard_negative"}, fam
    by_pair: dict[str, list[dict]] = {}
    for s in samples:
        by_pair.setdefault(s["pair_id"], []).append(s)
    assert all(
        len(v) == 2 and len({r["style"] for r in v}) == 1 and {r["role"] for r in v} == {"target", "hard_negative"}
        for v in by_pair.values()
    )
    # labels are the class output verbatim: re-plan the recipe and compare
    recipe = Recipe()
    reg = pipeline.build_registry(recipe)
    classes = resolve_classes(reg, recipe.classes)
    rh = run_json["recipe_sha256"]
    assert rh == recipe_sha256(frozen_recipe(recipe, [f"{c.name}@{c.version}" for c in classes]))
    ctx, slots, _ = build_context(recipe, classes, Path.cwd(), recipe_hash=rh)
    for s in samples[:: max(1, len(samples) // 5)][:5]:
        d = draw_slot(slots[s["slot"]], s["attempt"], ctx)
        assert s["label"] == (d.target if s["role"] == "target" else d.hard_negative)


def test_omicron_renders_with_lgrmath(default_run):
    _, run_json, samples, _, _ = default_run
    rows = [s for s in samples if s["error_class"] == "greek.omicron_o"]
    assert rows
    for s in rows:
        spec = run_json["styles"][s["style"]]
        style = to_style(StyleSpec(name=s["style"], font=spec["font"], size=spec["size"], packages=tuple(spec["packages"])), {"lgrmath"}, s["column_cm"])
        assert s["style_preamble_sha256"] == style.preamble_sha256


def test_exact_gate_positive_control(default_run):
    _, run_json, _, _, _ = default_run
    cells = run_json["survival"]["cells"]
    for font in FONTS:
        cell = cells[f"decorations.boldsymbol_bm@1|{font}"]
        assert cell["kept"] == 0 and set(cell["dropped"]) <= {"ambiguous-identical", "pair_partner_dropped"}, (font, cell)
        assert ["decorations.boldsymbol_bm@1", font] in run_json["survival"]["zero_yield"]


def test_near_identical_flag_only(default_run):
    _, run_json, _, ledger, _ = default_run
    cells = run_json["survival"]["cells"]
    il = {k: c for k, c in cells.items() if k.startswith("digits.I_l@1|")}
    print("I_l cells:", il)
    assert any(c["kept"] > 0 for c in il.values())
    print("near-identical cells:", {k: c["flags"]["near-identical"] for k, c in cells.items() if c["flags"].get("near-identical")})
    assert not [r for r in ledger if "near" in r["reason"]]  # a near-identical flag never drops a row


def test_flag_policy(tmp_path):
    recipe = _inline([r"\boldsymbol{x}+y"], ["decorations.boldsymbol_bm"], composition={"total": 1})
    flagged = run({**recipe, "qc": {"ambiguity": "flag"}}, tmp_path / "flag", cache=tmp_path / "c", max_parallel=2)
    _, samples, ledger = read_store(tmp_path / "flag")
    assert flagged.rows_kept == 2 and not ledger and all("ambiguous" in s["flags"] for s in samples)
    dropped = run({**recipe, "qc": {"ambiguity": "drop"}}, tmp_path / "drop", cache=tmp_path / "c", max_parallel=2)
    _, samples, ledger = read_store(tmp_path / "drop")
    assert dropped.rows_kept == 0 and {r["reason"] for r in ledger} == {"ambiguous-identical"}


def test_compile_failure_and_partner(tmp_path, monkeypatch):
    (tmp_path / "e2e_failing_plugin.py").write_text(
        "from glyphforge.errors import ConfusionPair\n"
        "def register_classes(reg):\n    reg.register(ConfusionPair('custom.fail_v', truth=r'\\fail', confusable='v', family='custom'))\n"
    )
    monkeypatch.syspath_prepend(tmp_path)
    run(
        {**_inline(["a_{v}+b"], ["custom.fail_v"], composition={"total": 1}), "plugins": ["e2e_failing_plugin"]},
        tmp_path / "out",
        cache=tmp_path / "c",
        max_parallel=2,
    )
    run_json, samples, ledger = read_store(tmp_path / "out")
    assert not samples
    assert {(r["role"], r["reason"]) for r in ledger} == {("target", "compile-failed"), ("hard_negative", "pair_partner_dropped")}
    assert run_json["plugins"] == ["e2e_failing_plugin"]


def test_library_route_with_mined_pair(tmp_path, monkeypatch):
    pairs = pairs_from_alignment([(r"\varphi", r"\phi", 5)])
    assert pairs[0].name == "mined.varphi_phi" and check_error_class(pairs[0], [r"a+\phi"]) == []
    reg = Registry()
    monkeypatch.setattr(pipeline, "DEFAULT_REGISTRY", reg)
    reg.register(pairs[0])
    result = run(_inline([r"a+\phi"], ["mined.varphi_phi"], composition={"total": 1}), tmp_path / "out", cache=tmp_path / "c", max_parallel=2)
    assert result.rows_kept > 0


def test_glyphfix_export_loads(default_run):
    out, run_json, samples, _, _ = default_run
    data = pytest.importorskip("glyphfix_math.train.data")
    trainset = pytest.importorskip("glyphfix_math.trainset")
    rows = data.read_trainset(out / "glyphfix" / "trainset.jsonl")
    assert len(rows) == len(samples)
    for row in rows:
        data.load_image(row, out / "glyphfix").close()
    group = trainset.summarize(rows)["counts"]["group"]
    assert group["error"] == group["control"] > 0
    import json

    manifest = json.loads((out / "glyphfix" / "export_manifest.json").read_text())
    assert manifest["control_glyphs_used"] == run_json["control_glyphs_used"]


def test_zero_yield_and_provenance(default_run):
    _, run_json, samples, _, _ = default_run
    for key in (
        "schema_version",
        "generator_version",
        "seed",
        "recipe",
        "recipe_sha256",
        "classes",
        "plugins",
        "styles",
        "canon_versions",
        "render_config",
        "counts",
        "survival",
        "control_glyphs_used",
    ):
        assert key in run_json, key
    for s in samples:
        assert s["recipe_sha256"] == run_json["recipe_sha256"] and s["generator_version"] == run_json["generator_version"]
        assert s["seed"] is not None and s["image_digest"] and s["rules"]
    zero = run_json["survival"]["zero_yield"]
    assert zero and all(isinstance(z, list) and len(z) == 2 for z in zero)
    for class_id, style in zero:
        assert run_json["survival"]["cells"][f"{class_id}|{style}"]["kept"] == 0
    print("zero_yield:", zero)
    print("counts:", run_json["counts"], "control_glyphs_used:", run_json["control_glyphs_used"])


def test_no_personal_data(default_run):
    out = default_run[0]
    needles = [str(Path.home()).encode(), b"@gmail.com"] + ([socket.gethostname().encode()] if len(socket.gethostname()) > 3 else [])
    for f in out.rglob("*"):
        if f.is_file():
            blob = f.read_bytes()
            assert not [n for n in needles if n in blob], f


def test_lgrmath_no_glyph_drift(tmp_path):
    items = ["a+b=c", "v", "o", "x_{1}+y"]
    plain = render_many(items, style=Style("cm", 10), cache=tmp_path / "a", max_parallel=2)
    lgr = render_many(items, style=Style("cm", 10, (r"\usepackage{lgrmath}",)), cache=tmp_path / "b", max_parallel=2)
    assert [r.status for r in plain + lgr] == ["rendered"] * 8
    assert [r.bitmap_sha256 for r in plain] == [r.bitmap_sha256 for r in lgr]
