from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from glyphforge.canon import canonical
from glyphforge.errors import builtin_registry
from glyphforge.export.leak import Blocklist, LeakError, base_id, build_blocklist, leak_check, load_blocklist
from glyphforge.plan.draw import DrawContext, Slot, build_context, draw_slot
from glyphforge.recipe.load import effective_styles
from glyphforge.recipe.schema import BlocklistPin, BoundsSpec, Recipe
from glyphforge.sources import Formula, ListSource

UPS = builtin_registry().get("greek.upsilon_v")


def _w(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")


def _row(aid, latex, split):
    return {"arxiv_id": aid, "latex": latex, "split": split}


def _tsv(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("id\tbucket\tv11_split\treason\tprimary_category\n" + "".join(f"{i}\tb\t{s}\t\tmath\n" for i, s in rows), "utf-8")


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "gfm"
    _w(r / "data/benchmark/records.jsonl", [_row("b1v2", "a_{v}", "benchmark")])
    _w(r / "data/benchmark/shards/records/s.jsonl", [_row("b2v1", "x ^ {2}", "benchmark")])
    _w(r / "data/corpus/shards/records/c.jsonl", [_row("d1v1", "dev=1", "dev"), _row("t1v1", "train=1", "train")])
    _w(
        r / "data/corpus_v11/shards/records/q.jsonl",
        [_row("f1v1", "fresh=1", "fresh_benchmark"), _row("p1v1", "page=1", "page_set"), _row("e1v1", "extra=1", "train_extra"), _row("x1v1", "x=1", "excluded")],
    )
    (r / "data/splits").mkdir(parents=True)
    (r / "data/splits/benchmark_ids.txt").write_text("math/0508005v2\n2101.00001\n", "utf-8")
    (r / "data/splits/quarantine_ids.txt").write_text("qq1v1\n", "utf-8")
    _tsv(r / "data/corpus_v11/split/assignment.tsv", [("a1v1", "fresh_benchmark"), ("a2v1", "train_extra")])
    _tsv(r / "data/corpus_v11/split_refresh1/assignment.tsv", [("a3v1", "page_set"), ("a4v1", "excluded")])
    return r


def _lines(path):
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()]


def test_base_id():
    assert base_id("2101.00001v3") == "2101.00001"
    assert base_id("math/0508005v2") == "math/0508005"
    assert base_id("2101.00001") == "2101.00001"


def test_build_blocklist_selects_sets_and_strips_versions(root, tmp_path):
    out = tmp_path / "out" / "bl.jsonl"
    meta = build_blocklist(root, out)
    rows = _lines(out)
    assert [(r["k"], r["v"]) for r in rows] == sorted((r["k"], r["v"]) for r in rows) and len({(r["k"], r["v"]) for r in rows}) == len(rows)
    formulas = {r["v"] for r in rows if r["k"] == "formula"}
    papers = {r["v"] for r in rows if r["k"] == "paper"}
    assert formulas == {canonical(s) for s in ("a_{v}", "x ^ {2}", "dev=1", "fresh=1", "page=1")}
    assert papers == {"b1", "b2", "d1", "f1", "p1", "math/0508005", "2101.00001", "qq1", "a1", "a3"}
    assert meta["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert meta["counts"] == {"formulas": len(formulas), "papers": len(papers)}
    assert meta["sets"] == {"benchmark_records": 1, "benchmark_shards": 1, "dev": 1, "fresh_benchmark": 1, "page_set": 1}
    assert json.loads(out.with_suffix(".meta.json").read_text()) == meta
    assert str(root) not in out.read_text() + out.with_suffix(".meta.json").read_text()
    with pytest.raises(FileExistsError):
        build_blocklist(root, out)
    again = tmp_path / "again.jsonl"
    build_blocklist(root, again)
    assert again.read_bytes() == out.read_bytes()


def test_build_blocklist_tolerates_missing_refresh_but_not_required_files(root, tmp_path):
    (root / "data/corpus_v11/split_refresh1/assignment.tsv").unlink()
    assert "a3" not in {r["v"] for r in _lines(_build(root, tmp_path / "a.jsonl"))}
    (root / "data/splits/benchmark_ids.txt").unlink()
    with pytest.raises(FileNotFoundError):
        build_blocklist(root, tmp_path / "b.jsonl")
    (root / "data/benchmark/records.jsonl").unlink()
    with pytest.raises(FileNotFoundError):
        build_blocklist(root, tmp_path / "c.jsonl")


def _build(root, out):
    build_blocklist(root, out)
    return out


def _pin(path, rows=None, name="bl.jsonl"):
    p = path / name
    if rows is not None:
        _w(p, rows)
    return BlocklistPin(path=name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())


ROWS = [{"k": "formula", "v": canonical("a_{v}")}, {"k": "paper", "v": "bad/001v3"}]


@pytest.mark.parametrize(
    ("rows", "pool"),
    [([ROWS[0]], "papers"), ([ROWS[1]], "formulas"), ([], "formulas")],
)
def test_load_blocklist_refuses_an_empty_pool(tmp_path, rows, pool):
    with pytest.raises(ValueError, match=f"0 {pool}"):
        load_blocklist(_pin(tmp_path, rows), tmp_path)


def test_load_blocklist_checks_sha_path_and_schema(tmp_path):
    pin = _pin(tmp_path, ROWS)
    bl = load_blocklist(pin, tmp_path)
    assert bl.sha256 == pin.sha256 and bl.papers == {"bad/001"}
    wrong = BlocklistPin(path="bl.jsonl", sha256="0" * 64)
    with pytest.raises(ValueError, match="blocklist sha256 mismatch") as e:
        load_blocklist(wrong, tmp_path)
    assert str(tmp_path) in str(e.value) and "0" * 64 in str(e.value)
    with pytest.raises(FileNotFoundError, match="0{64}"):
        load_blocklist(BlocklistPin(path="nope.jsonl", sha256="0" * 64), tmp_path)
    with pytest.raises(ValueError):
        load_blocklist(BlocklistPin(path=str(tmp_path / "bl.jsonl"), sha256=pin.sha256), tmp_path)
    for bad in ({"k": "other", "v": "x"}, {"k": "paper", "v": "x", "z": 1}, {"k": "paper", "v": 3}, {"k": "paper", "v": ""}):
        bad_pin = _pin(tmp_path, [ROWS[0], bad], "bad.jsonl")
        with pytest.raises(ValueError, match=r"bad\.jsonl:2"):
            load_blocklist(bad_pin, tmp_path)


def _bl(*formulas, papers=()):
    return Blocklist(frozenset(canonical(f) for f in formulas), frozenset(papers), "0" * 64)


def test_match_rule_and_order():
    bl = _bl("a_{v}", "q=1", papers=("bad/001",))
    assert bl.match("a_{v}", None, None) == ("formula", canonical("a_{v}"))
    assert bl.match("zzz", canonical("q=1"), None) == ("source", canonical("q=1"))
    assert bl.match("zzz", None, "bad/001v9") == ("paper", "bad/001")
    assert bl.match("zzz", "other", "fine1v1") is None
    assert bl.match("a_{v}", canonical("q=1"), "bad/001v1")[0] == "formula"
    assert bl.match("a_{ v }", None, None) is not None  # canonical-equal, not just string-equal
    assert bl.match("a", None, None) is None  # exact only: no short-formula exemption, no near-duplicate tier


def test_leak_check_reports_every_reason_in_order():
    bl = _bl("a_{v}", papers=("bad",))
    samples = [
        {"sample_id": "s0", "pair_id": "p0", "label": "clean", "source_canon": "c", "paper_id": "ok1v1"},
        {"sample_id": "s1", "pair_id": "p1", "label": "a_{v}", "source_canon": None, "paper_id": "badv2"},
        {"sample_id": "s2", "pair_id": "p2", "label": "clean", "paper_id": None},
    ]
    hits = leak_check(samples, bl)
    assert [(h["sample_id"], h["reason"]) for h in hits] == [("s1", "formula"), ("s1", "paper")]
    assert hits[0] == {"sample_id": "s1", "pair_id": "p1", "reason": "formula", "entry": canonical("a_{v}")}
    assert leak_check(samples[:1], bl) == []
    err = LeakError(hits)
    assert err.hits is hits and "2" in str(err)


# --- draw-time avoidance ------------------------------------------------------------------------------------------------------------------

ITEMS = tuple(Formula(latex=s, licence="CC-BY-4.0", paper_id=p, paper_version="v1", authors=("A",)) for s, p in (("v+a", "ok1v1"), ("v+b", "ok2v1"), ("v-c", "badv2"), ("2v+d", "ok3v1"), ("f+v", "ok4v1")))


def _ctx(blocklist) -> DrawContext:
    rec = Recipe()
    return DrawContext(
        0, (ListSource(ITEMS),), ("list",), (1,), effective_styles(rec), rec.structure, rec.typography.site_levels, BoundsSpec(), None, blocklist
    )


def _drawn(ctx):
    out = []
    for i in range(40):
        d = draw_slot(Slot(i, UPS, 0, 0, None, "pid"), 0, ctx)
        if d is not None:
            out.append(d)
    return out


def test_draws_skip_blocklisted_formulas_papers_and_labels():
    base = _drawn(_ctx(None))
    assert {d.formula.latex for d in base} == {f.latex for f in ITEMS}
    by_formula = _drawn(_ctx(_bl("v+a")))
    assert by_formula and all(d.formula.latex != "v+a" for d in by_formula)
    by_paper = _drawn(_ctx(_bl(papers=("bad",))))
    assert by_paper and all(d.formula.paper_id != "badv2" for d in by_paper)
    label = base[0].target
    by_label = _drawn(_ctx(_bl(label)))
    assert by_label and all(canonical(d.target) != canonical(label) for d in by_label)
    hard = base[0].hard_negative
    assert all(canonical(d.hard_negative) != canonical(hard) for d in _drawn(_ctx(_bl(hard))))


def test_no_blocklist_draws_are_unchanged():
    assert _drawn(_ctx(None)) == _drawn(dataclasses.replace(_ctx(None), blocklist=None))
    assert _ctx(None).blocklist is None


def _recipe(pin):
    return Recipe.model_validate(
        {"source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["v+a", "v+b"]}, "export": {"blocklist": pin.model_dump()}}
    )


def test_build_context_loads_pin_and_rejects_mismatch(tmp_path):
    pin = _pin(tmp_path, ROWS)
    ctx, _, _ = build_context(_recipe(pin), [UPS], tmp_path, recipe_hash="0" * 64)
    assert isinstance(ctx.blocklist, Blocklist) and ctx.blocklist.sha256 == pin.sha256
    with pytest.raises(ValueError, match="blocklist sha256 mismatch"):
        build_context(_recipe(BlocklistPin(path="bl.jsonl", sha256="1" * 64)), [UPS], tmp_path, recipe_hash="0" * 64)
    plain, _, _ = build_context(Recipe(), [UPS], tmp_path, recipe_hash="0" * 64)
    assert plain.blocklist is None


def test_build_blocklist_blocks_author_overlap_exclusions(root, tmp_path):
    rows = [
        ("o1v1", "excluded", "author_overlap_eval"),
        ("o2v2", "excluded", "author_overlap_v1_train"),
        ("o3v1", "excluded", "author_overlap_base_train"),
        ("n1v1", "excluded", "license"),
        ("n2v1", "train_extra", "author_overlap_eval"),
    ]
    path = root / "data/corpus_v11/split/assignment.tsv"
    path.write_text("id\tbucket\tv11_split\treason\tprimary_category\n" + "".join(f"{i}\tb\t{s}\t{r}\tmath\n" for i, s, r in rows), "utf-8")
    out = tmp_path / "bl.jsonl"
    meta = build_blocklist(root, out)
    papers = {r["v"] for r in _lines(out) if r["k"] == "paper"}
    assert {"o1", "o2", "o3"} <= papers
    assert not {"n1", "n2"} & papers
    assert meta["paper_files"]["data/corpus_v11/split/assignment.tsv"] == 3
