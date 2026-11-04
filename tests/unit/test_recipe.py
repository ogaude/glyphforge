"""Recipe schema, Formula validation, loader, hashing and JSON Schema freshness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from glyphforge.recipe import DEFAULT_STYLES, Recipe, StyleSpec, frozen_recipe, load_recipe, recipe_sha256, to_style
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
    assert r.qc.ambiguity == "drop" and r.export.formats == ("glyphfix",) and r.schema_version == 1
    assert r.styles == DEFAULT_STYLES and [s.name for s in r.styles] == ["default", "cmbright", "libertine"]


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
