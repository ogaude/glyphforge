from __future__ import annotations

import json
import os

import pytest

from glyphforge.recipe.schema import SourceSpec
from glyphforge.sources import Formula, ListSource, Source, load_source


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
