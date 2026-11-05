from pathlib import Path

import pytest

from glyphforge.recipe import load_recipe
from glyphforge.validate import validate_recipe

RECIPES = Path(__file__).resolve().parents[2] / "recipes"
FILES = sorted(RECIPES.glob("*.yaml"))
needs_source = pytest.mark.skipif(not (RECIPES / "source").is_dir(), reason="recipes/source/ not downloaded")


def test_recipes_exist():
    assert {f.name for f in FILES} >= {"grammar-small.yaml", "mix-small.yaml", "glyphforge-equations-v1.yaml"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_recipe_loads(path):
    load_recipe(path)


def test_grammar_small_validates_without_pins():
    res = validate_recipe(RECIPES / "grammar-small.yaml")
    assert res["ok"] and res["pins"] == [] and not res["problems"]


def test_dataset_recipe_shape():
    r = load_recipe(RECIPES / "glyphforge-equations-v1.yaml")
    grammar, mutation = r.source.parts
    assert (grammar.kind, mutation.kind, tuple(r.source.shares)) == ("grammar", "mutation", (0.3, 0.7))
    assert mutation.path == "source/glyphfix-train.jsonl" and len(mutation.sha256) == 64
    assert tuple(r.export.formats) == ("parquet",) and r.export.degrade is None
    assert r.export.blocklist.path == "source/blocklist.jsonl"


@needs_source
@pytest.mark.parametrize("name", ["glyphforge-equations-v1.yaml", "mix-small.yaml"])
def test_pinned_recipes_validate(name):
    res = validate_recipe(RECIPES / name)
    assert res["ok"], res["problems"]
