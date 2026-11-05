from __future__ import annotations

import hashlib
import json

import pytest

from glyphforge.errors import builtin_registry
from glyphforge.recipe.schema import SourceSpec
from glyphforge.rng import slot_rng
from glyphforge.sources import MutationSource, build_snapshot, load_snapshot, load_source
from glyphforge.sources.mutation import CONTRACT_KEYS


def _w(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")


def _paper(aid, split, quarantined=False):
    return {"arxiv_id": aid, "authors": [f"Author {aid}"], "split": split, "quarantined": quarantined}


def _row(aid, latex, split, env="equation", lic="CC-BY-4.0", builder="1"):
    return {
        "arxiv_id": aid, "builder_version": builder, "env": env, "latex": latex, "license_spdx": lic,
        "paper_version": "v1", "split": split, "width": 300, "height": 100,
    }  # fmt: skip


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "gfm"
    _w(r / "data/catalog/train_dev.jsonl", [_paper("p1", "train"), _paper("p2", "train"), _paper("pq", "train", True), _paper("pd", "dev"), _paper("pz", "train")])
    _w(r / "data/corpus_v11/catalog/batch-01.jsonl", [_paper("q1", "train_extra"), _paper("q2", "fresh_benchmark"), _paper("q3", "page_set")])
    _w(r / "data/corpus_v11/catalog/batch-01.excluded.jsonl", [_paper("qx", "train_extra")])
    _w(
        r / "data/corpus/shards/records/p1.jsonl",
        [
            _row("p1", "a_{v}+b", "train"),
            _row("p1", "x^2", "train", "displaymath", "CC0-1.0"),
            _row("p1", "a=b", "train", "align"),
            _row("p1", "c=d", "train", "gather"),
            _row("p1", "e=f", "train", "multline"),
            _row("p1", r"g=h\label{x}", "train"),
            _row("p1", r"u=v\notag", "train"),
            _row("p1", r"u=w\eqno(1)", "train"),
            _row("p1", r"u=y \leqno{(2)}", "train"),
            _row("p1", r"u=z\eqnotag", "train"),
            _row("p1", r"\foo{", "train"),
            _row("p1", "s=t", "dev"),
            _row("p1", "dup+1", "train"),
            _row("pq", "z=1", "train"),
            _row("pd", "z=2", "train"),
            _row("nocat", "z=3", "train"),
        ],
    )
    _w(r / "data/corpus/shards/records/p2.jsonl", [_row("p2", "dup+1", "train", lic="CC-BY-3.0"), _row("pz", "m=n", "train", lic="CC-BY-3.0")])
    _w(
        r / "data/corpus_v11/shards/records/q.jsonl",
        [
            _row("q1", "k=l", "train_extra", builder="2"),
            _row("q2", "bench=1", "fresh_benchmark", builder="2"),
            _row("q3", "page=1", "page_set", builder="2"),
            _row("q1", "pp=1", "train", builder="2"),
        ],
    )
    return r


def _rows(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_build_snapshot_gates_and_contract(root, tmp_path):
    out = tmp_path / "snap" / "s.jsonl"
    meta = build_snapshot(root, out)
    rows = _rows(out)
    assert all(tuple(r) == CONTRACT_KEYS and r["split"] == "train" for r in rows)
    assert rows == sorted(rows, key=lambda r: (r["paper_id"], r["latex"], r["env"]))
    by = {r["latex"]: r for r in rows}
    assert set(by) == {"a_{v}+b", "x^2", "a=b", "c=d", "dup+1", "m=n", "k=l", r"u=z\eqnotag"}
    assert [by[k]["env"] for k in ("x^2", "a=b", "c=d")] == ["equation*", "align*", "gather*"]
    assert by["k=l"]["authors"] == ["Author q1"]
    assert meta["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert json.loads(out.with_suffix(".meta.json").read_text()) == meta
    p = meta["pools"]
    assert p["v1"]["read"] == 18 and p["v1"]["builder_version"] == "1" and p["v11"]["builder_version"] == "2"
    assert p["v1"]["rejected"] == {"env": 1, "numbering": 4, "invalid_formula": 1, "split": 2, "quarantined": 1, "no_catalog": 1}
    assert p["v11"]["rejected"] == {"split": 3}
    for q in p.values():
        assert q["rows"] + sum(q["rejected"].values()) == q["read"]
    assert meta["rows"] == len(rows) and set(meta["reference_crops"]) == {"width_q", "height_q", "area_below_floor"}
    assert str(tmp_path) not in out.read_text("utf-8") + out.with_suffix(".meta.json").read_text()


def test_build_snapshot_deterministic_and_refuses_overwrite(root, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    build_snapshot(root, a)
    build_snapshot(root, b)
    assert a.read_bytes() == b.read_bytes()
    with pytest.raises(FileExistsError):
        build_snapshot(root, a)


def test_build_snapshot_rejects_wrong_builder_version(root, tmp_path):
    _w(root / "data/corpus_v11/shards/records/bad.jsonl", [_row("q1", "u=v", "train_extra", builder="1")])
    with pytest.raises(ValueError, match="bad.jsonl"):
        build_snapshot(root, tmp_path / "s.jsonl")


def _spec(path, sha) -> SourceSpec:
    return SourceSpec(kind="mutation", path=path, sha256=sha)


def _contract(latex, split="train", licence="CC-BY-4.0", **kw):
    return {"authors": ["A"], "env": "equation*", "latex": latex, "licence": licence, "paper_id": "1", "paper_version": "v1", "split": split} | kw


def test_load_snapshot_pins_sha256_before_parsing(tmp_path, monkeypatch):
    _w(tmp_path / "s.jsonl", [_contract("a_{v}")])
    monkeypatch.setattr(json, "loads", lambda *_: pytest.fail("parsed before the sha check"))
    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_snapshot(_spec("s.jsonl", "0" * 64), tmp_path)


def test_load_snapshot_path_checks(tmp_path):
    _w(tmp_path / "s.txt", [])
    with pytest.raises(ValueError, match="inside"):
        load_snapshot(_spec("../s.jsonl", "0" * 64), tmp_path / "sub")
    with pytest.raises(ValueError, match=r"\.jsonl"):
        load_snapshot(_spec("s.txt", "0" * 64), tmp_path)


def test_load_snapshot_gate_counts(tmp_path):
    rows = [
        _contract("a_{v}"),
        _contract("dev1", "dev"),
        _contract("ex1", "train_extra"),
        _contract("mit", licence="MIT"),
        _contract("nc", licence="CC-BY-NC-4.0"),
        _contract("a_{v}"),
        _contract("ok2", licence="CC0-1.0", authors=[]),
    ]
    _w(tmp_path / "s.jsonl", rows)
    sha = hashlib.sha256((tmp_path / "s.jsonl").read_bytes()).hexdigest()
    src = load_source(_spec("s.jsonl", sha), tmp_path)
    assert isinstance(src, MutationSource)
    assert [r["latex"] for r in src.rows] == ["a_{v}", "ok2"]
    assert src.rejected == {"split": 2, "licence": 2, "duplicate": 1}


@pytest.mark.parametrize("bad", [{"latex": "x"}, _contract("x") | {"extra": 1}])
def test_load_snapshot_rejects_bad_keys(tmp_path, bad):
    _w(tmp_path / "s.jsonl", [_contract("ok"), bad])
    sha = hashlib.sha256((tmp_path / "s.jsonl").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=r"s\.jsonl:2"):
        load_snapshot(_spec("s.jsonl", sha), tmp_path)


def test_mutation_draw_keeps_row_attribution(tmp_path):
    cls = builtin_registry().get("greek.upsilon_v")
    _w(tmp_path / "s.jsonl", [_contract("a_{v}+b", paper_id="2101.0001", authors=["Ada L"]), _contract("x+y")])
    sha = hashlib.sha256((tmp_path / "s.jsonl").read_bytes()).hexdigest()
    src = load_snapshot(_spec("s.jsonl", sha), tmp_path)
    f = src.draw(cls, slot_rng(1, "source", 0), level="A", multiline=True)
    assert (f.latex, f.licence, f.paper_id, f.paper_version, f.authors) == ("a_{v}+b", "CC-BY-4.0", "2101.0001", "v1", ("Ada L",))
    assert MutationSource(({"latex": r"\foo{", **{k: v for k, v in _contract("x").items() if k not in ("latex", "split")}},), sha, {}).draw(
        type("C", (), {"name": "t", "version": "1", "sites": lambda self, s: (1,)})(), slot_rng(1, "source", 0)
    ) is None  # fmt: skip


def test_snapshot_cli(root, tmp_path, monkeypatch, capsys):
    pytest.importorskip("typer")
    from glyphforge.cli import main

    monkeypatch.setattr("sys.argv", ["glyphforge", "snapshot", str(root), str(tmp_path / "o.jsonl")])
    with pytest.raises(SystemExit) as exc:
        main()
    out = capsys.readouterr().out
    assert exc.value.code == 0 and "sha256 " in out and "rows 9" in out
