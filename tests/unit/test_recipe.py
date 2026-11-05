"""Recipe schema, Formula validation, loader, hashing and JSON Schema freshness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from glyphforge.recipe import DEFAULT_STYLES, DegradeSpec, Recipe, StyleSpec, effective_styles, frozen_recipe, load_recipe, recipe_sha256, to_style
from glyphforge.render.style import Style
from glyphforge.sources import Formula

CC0 = "CC0-1.0"


def test_formula_valid_defaults():
    f = Formula(latex="a_{v}+b", licence=CC0)
    assert f.env == "equation*" and f.authors == ()


def test_formula_cc_by_needs_provenance():
    with pytest.raises(ValidationError, match="paper_id"):
        Formula(latex="x", licence="CC-BY-4.0")
    Formula(latex="x", licence="CC-BY-4.0", paper_id="2401.00001", paper_version="v2", authors=("A. B.",))


@pytest.mark.parametrize(
    "kw",
    [
        {"latex": r"\input{/etc/passwd}", "licence": CC0},
        {"latex": "{x", "licence": CC0},
        {"latex": "x", "licence": "MIT"},
        {"latex": "x", "licence": CC0, "env": "eqnarray"},
    ],
)
def test_formula_rejects(kw):
    with pytest.raises(ValidationError):
        Formula(**kw)


def test_recipe_defaults():
    r = Recipe.model_validate({})
    assert (r.seed, r.source.kind, r.classes, r.plugins, r.entry_points) == (0, "builtin", None, (), False)
    assert r.qc.ambiguity == "drop" and r.export.formats == () and r.schema_version == 3
    assert r.styles is None and r.structure.kinds == {"display": 1.0, "inline": 0.0, "numbered": 0.0}
    assert (r.composition.total, r.composition.shares, r.composition.hard_negative_ratio, r.composition.attempt_cap) == (100, None, 1.0, 5)
    assert r.bounds.token_cap == 440 and r.bounds.max_depth == 6 and r.bounds.max_scripts == 12 and r.render.pad_px == 0
    assert r.typography.fonts == {"cm": 55, "lmodern": 15, "newtx": 10, "mathpazo": 7, "stix2": 7, "libertine": 6}
    assert r.typography.sizes == {8: 3, 9: 7, 10: 35, 11: 25, 12: 30} and r.typography.site_levels["base"] == 60
    assert Recipe.model_validate({"typography": {"fonts": {"cm": 1}}}).typography.sizes == r.typography.sizes


@pytest.mark.parametrize("data", [{"bogus": 1}, {"seed": "1"}, {"qc": {"ambiguity": False}}, {"plugins": ["os; rm"]}])
def test_recipe_rejects(data):
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


def test_recipe_plugin_module_ok():
    assert Recipe.model_validate({"plugins": ["my_pkg.classes"]}).plugins == ("my_pkg.classes",)


def test_source_inline():
    r = Recipe.model_validate({"source": {"kind": "inline", "licence": CC0, "formulas": ["a+b", {"latex": "x_l", "env": "align*"}]}})
    assert [f.licence for f in r.source.formulas] == [CC0, CC0] and r.source.formulas[1].env == "align*"


@pytest.mark.parametrize(
    "src",
    [
        {"kind": "inline", "formulas": ["a"]},
        {"kind": "inline", "licence": CC0, "formulas": [{"latex": "a", "licence": "CC-BY-4.0"}]},
        {"kind": "file", "licence": CC0},
        {"kind": "file", "licence": CC0, "path": "x.jsonl", "formulas": ["a"]},
        {"kind": "builtin", "licence": CC0},
    ],
)
def test_source_rejects(src):
    with pytest.raises(ValidationError):
        Recipe.model_validate({"source": src})


def test_styles():
    for bad in ({"font": "comic", "size": 12}, {"font": "cm", "size": 13}, {"font": "cm", "size": 12, "packages": ["bad pkg"]}):
        with pytest.raises(ValidationError):
            StyleSpec(name="x", **bad)
    assert StyleSpec(name="x", font="cm", size=12, packages=("lgrmath",)).packages == ("lgrmath",)
    with pytest.raises(ValidationError):
        Recipe.model_validate({"styles": [{"name": "a", "font": "cm", "size": 12}] * 2})


# --- loader / hash / style / schema ---

def test_load_yaml_toml_equal(tmp_path):
    (tmp_path / "r.yaml").write_text("seed: 3\nqc:\n  ambiguity: flag\n")
    (tmp_path / "r.toml").write_text('seed = 3\n[qc]\nambiguity = "flag"\n')
    assert load_recipe(tmp_path / "r.yaml") == load_recipe(tmp_path / "r.toml")


def test_load_errors(tmp_path):
    (tmp_path / "r.json").write_text("{}")
    (tmp_path / "list.yaml").write_text("- 1\n")
    (tmp_path / "empty.yaml").write_text("")
    (tmp_path / "no.yaml").write_text("qc:\n  ambiguity: no\n")
    with pytest.raises(ValueError, match=r"\.yaml"):
        load_recipe(tmp_path / "r.json")
    with pytest.raises(ValueError, match="mapping"):
        load_recipe(tmp_path / "list.yaml")
    with pytest.raises(ValidationError):
        load_recipe(tmp_path / "no.yaml")
    assert load_recipe(tmp_path / "empty.yaml") == Recipe()


def test_recipe_hash():
    a = Recipe.model_validate({"seed": 1, "qc": {"ambiguity": "drop"}})
    b = Recipe.model_validate({"qc": {}, "seed": 1})
    fa = frozen_recipe(a, ["greek.upsilon_v@1"])
    assert fa["classes"] == ["greek.upsilon_v@1"]
    h = recipe_sha256(fa)
    assert len(h) == 64 and h == recipe_sha256(frozen_recipe(b, ["greek.upsilon_v@1"]))
    assert h != recipe_sha256(frozen_recipe(b, ["greek.upsilon_v@2"]))
    assert h != recipe_sha256(frozen_recipe(Recipe(seed=2), ["greek.upsilon_v@1"]))


def test_to_style():
    assert to_style(DEFAULT_STYLES[0]) == Style() and to_style(DEFAULT_STYLES[0]).is_default
    assert to_style(DEFAULT_STYLES[1]) == Style("cm", 12, (r"\usepackage{cmbright}",))
    assert to_style(DEFAULT_STYLES[1], {"lgrmath"}).extra == (r"\usepackage{cmbright}", r"\usepackage{lgrmath}")
    with pytest.raises(ValueError):
        to_style(DEFAULT_STYLES[0], {"bad pkg"})


def test_schema_json_fresh():
    path = Path(__file__).parents[2] / "src/glyphforge/recipe/schema.json"
    assert path.read_text(encoding="utf-8") == json.dumps(Recipe.model_json_schema(), indent=2, sort_keys=True) + "\n"


MUT = {"kind": "mutation", "path": "s.jsonl", "sha256": "a" * 64}


def _src(**kw):
    return Recipe.model_validate({"source": kw})


def test_schema1_rejected():
    with pytest.raises(ValidationError):
        Recipe.model_validate({"schema_version": 1})


@pytest.mark.parametrize(
    "src",
    [
        {"kind": "mutation", "sha256": "a" * 64},
        {"kind": "mutation", "path": "s.jsonl"},
        {"kind": "mutation", "path": "s.jsonl", "sha256": "A" * 64},
        {"kind": "mutation", "path": "s.jsonl", "sha256": "a" * 63},
        {**MUT, "licence": CC0},
        {"kind": "grammar", "licence": CC0},
        {"kind": "builtin", "domains": {"math": 1}},
        {"kind": "builtin", "sha256": "a" * 64},
        {"kind": "grammar", "max_sites": 1},
        {**MUT, "max_sites": 4},
        {"kind": "mix", "parts": [{"kind": "grammar"}, {"kind": "grammar"}], "shares": [0.5, 0.6]},
        {"kind": "mix", "parts": [{"kind": "grammar"}, {"kind": "mix"}], "shares": [0.5, 0.5]},
        {"kind": "mix", "parts": [{"kind": "grammar"}], "shares": [0.5, 0.5]},
        {"kind": "mix", "parts": [{"kind": "grammar"}] * 3, "shares": [0.5, 0.5]},
        {"kind": "mix", "parts": [{"kind": "grammar"}, {"kind": "grammar", "domains": {"math": 1}}]},
    ],
)
def test_source2_rejects(src):
    with pytest.raises(ValidationError):
        _src(**src)


def test_mix_shares():
    g = {"kind": "grammar"}
    assert _src(kind="mix", parts=[g, MUT]).source.shares == (0.3, 0.7)
    assert _src(kind="mix", parts=[MUT, g]).source.shares == (0.7, 0.3)
    assert _src(kind="mix", parts=[g, g], shares=[0.5, 0.5]).source.shares == (0.5, 0.5)
    assert _src(kind="grammar", domains={"math": 2, "physics": 1}).source.domains == {"math": 2, "physics": 1}
    assert _src(**MUT, max_sites=3).source.max_sites == 3


def test_mutation_sha_in_recipe_hash():
    a, b = _src(**MUT), _src(**{**MUT, "sha256": "b" * 64})
    assert recipe_sha256(frozen_recipe(a, [])) != recipe_sha256(frozen_recipe(b, []))


@pytest.mark.parametrize(
    "data",
    [
        {"composition": {"shares": {"a": 0.5, "b": 0.4}}},
        {"composition": {"shares": {"a": -0.5, "b": 1.5}}},
        {"composition": {"hard_negative_ratio": 0.9}},
        {"composition": {"attempt_cap": 0}},
        {"composition": {"attempt_cap": 21}},
        {"composition": {"total": 0}},
        {"typography": {"fonts": {"cm": 0}}},
        {"typography": {"fonts": {"cm": -1}}},
        {"typography": {"fonts": {"comic": 1}}},
        {"typography": {"sizes": {13: 1}}},
        {"structure": {"column_cm": {40: 1}}},
        {"bounds": {"max_tokens": 100, "token_margin": 100}},
        {"render": {"pad_px": -1}},
        {"styles": [{"name": "a", "font": "cm", "size": 12, "weight": 0}]},
    ],
)
def test_sections_reject(data):
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


def test_effective_styles():
    es = effective_styles(Recipe())
    assert len(es) == 30 and es[0][0].name == "cm-8pt" and es[-1][0].name == "stix2-12pt"
    assert es[0][1] == 55 * 3 and es[0][0].weight == es[0][1]
    assert [s.name for s, _ in effective_styles(Recipe.model_validate({"typography": {"fonts": {"cm": 1, "lmodern": 0}}}))] == [
        f"cm-{z}pt" for z in (8, 9, 10, 11, 12)
    ]
    explicit = Recipe.model_validate({"styles": [{"name": "b", "font": "cm", "size": 12, "weight": 3}, {"name": "a", "font": "cm", "size": 11}]})
    assert [(s.name, w) for s, w in effective_styles(explicit)] == [("b", 3), ("a", 1)]


def test_effective_styles_key_order_invariant():
    a = Recipe.model_validate({"typography": {"fonts": {"cm": 2, "newtx": 1}}})
    b = Recipe.model_validate({"typography": {"fonts": {"newtx": 1, "cm": 2}}})
    assert effective_styles(a) == effective_styles(b)
    assert recipe_sha256(frozen_recipe(a, [])) == recipe_sha256(frozen_recipe(b, []))


def test_to_style_column():
    spec = StyleSpec(name="x", font="cm", size=12)
    st = to_style(spec, column_cm=12)
    assert st.column_cm == 12 and st.extra == () and not st.is_default
    assert st.preamble_sha256 != to_style(spec).preamble_sha256 != to_style(spec, column_cm=8.5).preamble_sha256
    assert to_style(spec, column_cm=None) == to_style(spec)


_PIN = {"path": "b.jsonl", "sha256": "a" * 64}


def test_export_defaults_and_formats():
    e = Recipe().export
    assert (e.formats, e.blocklist, e.degrade, e.shard_mb) == ((), None, None, 500)
    ok = Recipe.model_validate({"export": {"formats": ["glyphfix", "parquet"], "blocklist": _PIN}})
    assert ok.export.formats == ("glyphfix", "parquet")


@pytest.mark.parametrize(
    "export",
    [
        {"formats": ["parquet"]},
        {"formats": ["parquet", "parquet"], "blocklist": _PIN},
        {"blocklist": {"path": "b.jsonl", "sha256": "xyz"}},
        {"blocklist": {"path": "b.jsonl"}},
        {"shard_mb": 0},
        {"bogus": 1},
    ],
)
def test_export_rejects(export):
    with pytest.raises(ValidationError):
        Recipe.model_validate({"export": export})


def test_export_needs_blocklist_message():
    with pytest.raises(ValidationError, match="blocklist"):
        Recipe.model_validate({"export": {"formats": ["parquet"]}})


def test_degrade_defaults_and_caps():
    s = DegradeSpec(blur={})
    assert (s.blur.min, s.blur.max, s.blur.p, s.rotate) == (0.3, 0.8, 0.5, None)
    for bad in ({"rotate": {"max": 5}}, {"blur": {"min": 0.9, "max": 0.4}}, {"jpeg": {"min": 30}}, {"clean_share": 2}):
        with pytest.raises(ValidationError):
            DegradeSpec.model_validate(bad)
