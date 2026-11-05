from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from glyphforge.errors import builtin_registry, check_error_class
from glyphforge.recipe.schema import SourceSpec
from glyphforge.sources import Formula, ListSource, Source, builtin_seed, load_source


def _f(latex: str) -> Formula:
    return Formula(latex=latex, licence="CC0-1.0")


def _file_spec(licence: str = "CC0-1.0", path: str = "f.jsonl") -> SourceSpec:
    return SourceSpec(kind="file", licence=licence, path=path)


def _write(path, *rows) -> None:
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n", "utf-8")


def test_list_source_order_and_protocol():
    a, b = _f("a+b"), _f("c+d")
    assert ListSource((a, b)).formulas() == (a, b)
    assert isinstance(ListSource(()), Source)


def test_list_source_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate"):
        ListSource((_f("a+b"), _f("a+b")))


def test_inline_spec_returns_formulas_in_order(tmp_path):
    spec = SourceSpec(kind="inline", licence="CC0-1.0", formulas=["a+b", "c+d"])
    assert [f.latex for f in load_source(spec, tmp_path).formulas()] == ["a+b", "c+d"]


def test_file_source_reads_jsonl_and_injects_licence(tmp_path):
    _write(tmp_path / "f.jsonl", {"latex": "a+b"}, "", {"latex": "c+d", "env": "align*"})
    got = load_source(_file_spec(), tmp_path).formulas()
    assert [(f.latex, f.env, f.licence) for f in got] == [("a+b", "equation*", "CC0-1.0"), ("c+d", "align*", "CC0-1.0")]


def test_file_source_rejects_conflicting_row_licence(tmp_path):
    _write(tmp_path / "f.jsonl", {"latex": "a+b"}, {"latex": "c+d", "licence": "CC-BY-4.0"})
    with pytest.raises(ValueError, match=r"f\.jsonl:2"):
        load_source(_file_spec(), tmp_path)


def test_file_source_cc_by_requires_attribution(tmp_path):
    _write(tmp_path / "f.jsonl", {"latex": "a+b", "paper_id": "1", "paper_version": "v1", "authors": ["A"]}, {"latex": "c+d"})
    with pytest.raises(ValueError, match=r"f\.jsonl:2"):
        load_source(_file_spec("CC-BY-4.0"), tmp_path)


def test_file_source_cc_by_with_attribution(tmp_path):
    _write(tmp_path / "f.jsonl", {"latex": "a+b", "paper_id": "1", "paper_version": "v1", "authors": ["A"]})
    assert load_source(_file_spec("CC-BY-4.0"), tmp_path).formulas()[0].authors == ("A",)


def test_file_source_bad_json_names_line(tmp_path):
    _write(tmp_path / "f.jsonl", "{not json")
    with pytest.raises(ValueError, match=r"f\.jsonl:1"):
        load_source(_file_spec(), tmp_path)


@pytest.mark.parametrize("path", ["/etc/passwd", "../x.jsonl", "sub/../../x.jsonl"])
def test_file_source_path_containment(tmp_path, path):
    base = tmp_path / "recipe"
    base.mkdir()
    _write(tmp_path / "x.jsonl", {"latex": "a+b"})
    with pytest.raises(ValueError, match="inside the recipe directory"):
        load_source(_file_spec(path=path), base)


def test_file_source_symlink_escape(tmp_path):
    base = tmp_path / "recipe"
    base.mkdir()
    _write(tmp_path / "x.jsonl", {"latex": "a+b"})
    os.symlink(tmp_path / "x.jsonl", base / "link.jsonl")
    with pytest.raises(ValueError, match="inside the recipe directory"):
        load_source(_file_spec(path="link.jsonl"), base)


def test_file_source_suffix(tmp_path):
    (tmp_path / "f.txt").write_text('{"latex": "a+b"}\n')
    with pytest.raises(ValueError, match=r"\.jsonl"):
        load_source(_file_spec(path="f.txt"), tmp_path)


def test_file_source_duplicate_latex(tmp_path):
    _write(tmp_path / "f.jsonl", {"latex": "a+b"}, {"latex": "a+b"})
    with pytest.raises(ValueError, match="duplicate"):
        load_source(_file_spec(), tmp_path)


@pytest.fixture(scope="module")
def registry():
    return builtin_registry()


@pytest.fixture(scope="module")
def seed_latex():
    return [f.latex for f in builtin_seed()]


def test_seed_set_size_and_licence():
    seed = builtin_seed()
    assert 50 <= len(seed) <= 100
    assert {f.licence for f in seed} == {"CC0-1.0"}
    assert len({f.latex for f in seed}) == len(seed)
    assert max(len(f.latex) for f in seed) <= 200


def test_seed_set_is_the_builtin_source(tmp_path):
    assert load_source(SourceSpec(), tmp_path).formulas() == builtin_seed()


def test_seed_set_display_envs_and_probes(seed_latex):
    display = [f for f in builtin_seed() if f.env != "equation*" and ("&" in f.latex or "\\\\" in f.latex)]
    assert len(display) >= 6
    assert {"a_{I}+b", "a_{l}+b", "a_{1}+b", r"\boldsymbol{x}+y", r"\bm{x}+y"} <= set(seed_latex)


def test_seed_set_covers_every_builtin_class(registry, seed_latex):
    assert [n for n in registry.names() if not any(registry.get(n).sites(x) for x in seed_latex)] == []


def test_seed_set_site_budget(registry, seed_latex):
    totals: dict[str, int] = {}
    for n in registry.names():
        cls = registry.get(n)
        totals[cls.family] = totals.get(cls.family, 0) + sum(len(cls.sites(x)) for x in seed_latex)
    assert sum(totals.values()) <= 400, totals


@pytest.mark.parametrize("name", builtin_registry().names())
def test_seed_set_passes_class_contract(registry, seed_latex, name):
    assert check_error_class(registry.get(name), seed_latex) == []


def test_list_source_duplicate_check_is_linear():
    import time

    items = tuple(_f(f"x_{{{i}}}+y") for i in range(50_000))
    t = time.perf_counter()
    ListSource(items)
    assert time.perf_counter() - t < 2


def test_list_source_draw_class_aware_and_deterministic():
    from glyphforge.rng import slot_rng

    cls = builtin_registry().get("greek.upsilon_v")
    src = ListSource((_f("a_{v}+b"), _f("x+y"), _f("v^2")))
    got = {src.draw(cls, slot_rng(s, "source", 0), level=None, multiline=True).latex for s in range(20)}
    assert got and got <= {"a_{v}+b", "v^2"}
    assert src.draw(cls, slot_rng(1, "source", 0)) == src.draw(cls, slot_rng(1, "source", 0))
    assert ListSource((_f("x+y"),)).draw(cls, slot_rng(1, "source", 0)) is None


def test_draw_site_index_built_once():
    from glyphforge.rng import slot_rng

    calls = []

    class Counting:
        name, version = "t.count", "1"

        def sites(self, latex):
            calls.append(latex)
            return ("s",) if "v" in latex else ()

    src = ListSource((_f("v+1"), _f("x+y")))
    src.draw(Counting(), slot_rng(1, "source", 0))
    n = len(calls)
    src.draw(Counting(), slot_rng(2, "source", 0))
    assert len(calls) == n


def test_one_pass_index_equals_the_per_class_scan(registry, seed_latex):
    from glyphforge.rng import slot_rng

    classes = [registry.get(n) for n in registry.names()]
    src = ListSource(builtin_seed())
    src.index(classes)
    for cls in classes:
        assert src._index[(cls.name, cls.version)] == tuple(i for i, s in enumerate(seed_latex) if cls.sites(s))
    lazy = ListSource(builtin_seed())
    for cls in classes:
        assert src.draw(cls, slot_rng(3, "source", 0)) == lazy.draw(cls, slot_rng(3, "source", 0))


def test_index_progress_and_tokenisation_shared_across_classes(registry):
    from glyphforge.errors.api import token_spans

    rows = tuple(_f(f"v_{{{i}}}'+x^2") for i in range(2500))
    classes = [registry.get(n) for n in registry.names()]
    token_spans.cache_clear()
    seen = []
    ListSource(rows).index(classes, lambda *a: seen.append(a))
    assert token_spans.cache_info().misses <= len(rows) + 8
    assert seen == [("index", 1000, 2500), ("index", 2000, 2500)]


def test_list_source_is_a_draw_source():
    from glyphforge.sources import DrawSource

    assert isinstance(ListSource(builtin_seed()), DrawSource)


def test_sources_import_skips_the_image_stack():
    code = "import sys, glyphforge.sources; assert not {'numpy', 'PIL'} & set(sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
