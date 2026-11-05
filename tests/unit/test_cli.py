import hashlib
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("typer")
import yaml
from typer.testing import CliRunner

from glyphforge import pipeline
from glyphforge._cli import build_app
from glyphforge.canon import canonical

SCHEMA = Path(__file__).resolve().parents[2] / "src" / "glyphforge" / "recipe" / "schema.json"
FIX = Path(__file__).resolve().parents[1] / "fixtures"
FORMS = ["a_{v}+v", "b+v+c", "v-d", "e*v", "v+f", "2v+g", "h+v"]
runner = CliRunner()
app = build_app()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def rdir(tmp_path):
    d = tmp_path / "rec"
    d.mkdir()
    shutil.copy(FIX / "blocklist.jsonl", d / "blocklist.jsonl")
    return d


def _recipe(rdir, name="r.yaml", formats=("glyphfix",), forms=FORMS, total=6, sha=None, **kw):
    r = {
        "seed": 3,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": forms},
        "classes": ["greek.upsilon_v", "greek.nu_v"],
        "styles": [{"name": "default", "font": "cm", "size": 12}],
        "structure": {"kinds": {"display": 1.0}},
        "composition": {"total": total},
        "export": {"formats": list(formats), "blocklist": {"path": "blocklist.jsonl", "sha256": sha or _sha(rdir / "blocklist.jsonl")}},
        **kw,
    }
    path = rdir / name
    path.write_text(yaml.safe_dump(r), encoding="utf-8")
    return path


def _run(*args):
    return runner.invoke(app, [str(a) for a in args])


def test_help_lists_commands():
    out = _run("--help").stdout
    for c in ("run", "plan", "validate", "export", "preview", "blocklist", "snapshot", "doctor"):
        assert c in out


def test_help_documents_blocklist_resolution():
    for cmd in ("run", "export"):
        out = " ".join(_run(cmd, "--help").stdout.split())
        assert "sha256" in out and "blocklist path resolves against" in out


def test_run_exports_and_refuses(rdir, tmp_path, fake):
    r = _recipe(rdir)
    res = _run("run", r, tmp_path / "out", "--cache", tmp_path / "c")
    assert res.exit_code == 0, res.stderr
    assert "recipe_sha256" in res.stdout and "rows kept" in res.stdout and "export" in res.stdout
    assert (tmp_path / "out" / "export" / "glyphfix" / "trainset.jsonl").is_file()
    again = _run("run", r, tmp_path / "out", "--cache", tmp_path / "c")
    assert again.exit_code == 2 and "already exists" in again.stderr


def test_run_no_export(rdir, tmp_path, fake):
    res = _run("run", _recipe(rdir), tmp_path / "out", "--no-export", "--cache", tmp_path / "c")
    assert res.exit_code == 0 and (tmp_path / "out" / "run.json").is_file() and not (tmp_path / "out" / "export").exists()


def test_run_resumes_and_refuses_foreign_journal(rdir, tmp_path, fake, monkeypatch):
    real = pipeline.render_many
    state = {"n": 0}

    def flaky(*a, **kw):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("killed")
        return real(*a, **kw)

    r = _recipe(rdir, forms=[*FORMS[:2], r"v+\fail", r"v+\fail+b"], formats=())
    monkeypatch.setattr(pipeline, "render_many", flaky)
    assert _run("run", r, tmp_path / "out", "--cache", tmp_path / "c").exit_code != 0
    assert not (tmp_path / "out" / "run.json").exists()
    other = _recipe(rdir, "o.yaml", total=8, forms=[*FORMS[:2], r"v+\fail", r"v+\fail+b"], formats=())
    res = _run("run", other, tmp_path / "out", "--cache", tmp_path / "c")
    assert res.exit_code == 2 and "different recipe" in res.stderr
    state["n"] = -99
    assert _run("run", r, tmp_path / "out", "--cache", tmp_path / "c").exit_code == 0
    assert (tmp_path / "out" / "run.json").is_file()


def test_run_shortfall_exits_zero(rdir, tmp_path, fake):
    res = _run("run", _recipe(rdir, forms=[r"v+\fail", r"v+\fail+b"], total=6, formats=()), tmp_path / "out", "--cache", tmp_path / "c")
    assert res.exit_code == 0 and "shortfall" in res.stderr


def test_run_blocklist_hit(rdir, tmp_path, fake, monkeypatch):
    from glyphforge.export.leak import LeakError

    def gate(*a, **k):
        raise LeakError([{"sample_id": "s0", "pair_id": "p0", "reason": "formula", "entry": "x"}])

    monkeypatch.setattr(pipeline, "export_store", gate)
    res = _run("run", _recipe(rdir), tmp_path / "out", "--cache", tmp_path / "c")
    assert res.exit_code == 1 and res.stdout.startswith("leak s0 p0 formula x")
    assert (tmp_path / "out" / "run.json").is_file()


@pytest.fixture
def store(rdir, tmp_path, fake):
    assert _run("run", _recipe(rdir), tmp_path / "st", "--no-export", "--cache", tmp_path / "c").exit_code == 0
    return tmp_path / "st"


def test_export_frozen_and_format(store, rdir, tmp_path, monkeypatch):
    monkeypatch.chdir(rdir)
    res = _run("export", store, tmp_path / "o1")
    assert res.exit_code == 0, res.stderr
    assert (tmp_path / "o1" / "glyphfix" / "export_manifest.json").is_file()
    res = _run("export", store, tmp_path / "o2", "--format", "parquet", "--json")
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout)[0]["format"] == "hf-parquet" and (tmp_path / "o2" / "parquet").is_dir()


def test_export_blocklist_resolves_against_cwd_without_recipe(store, tmp_path):
    res = _run("export", store, tmp_path / "o")
    assert res.exit_code == 2 and "blocklist not found" in res.stderr and _sha(FIX / "blocklist.jsonl") in res.stderr


def test_export_no_format(rdir, tmp_path, fake, monkeypatch):
    assert _run("run", _recipe(rdir, formats=()), tmp_path / "st", "--cache", tmp_path / "c").exit_code == 0
    res = _run("export", tmp_path / "st", tmp_path / "o")
    assert res.exit_code == 2 and "no export format" in res.stderr


def test_export_recipe_section_and_manifest(store, rdir, tmp_path):
    other = _recipe(rdir, "e.yaml", formats=("glyphfix",))
    shutil.copy(rdir / "blocklist.jsonl", rdir / "x.jsonl")
    res = _run("export", store, tmp_path / "o", "--recipe", other, "--json")
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout)[0]["export_spec_from_store"] is True
    r = yaml.safe_load(other.read_text())
    r["export"]["shard_mb"] = 7
    other.write_text(yaml.safe_dump(r))
    res = _run("export", store, tmp_path / "o3", "--recipe", other, "--json")
    assert res.exit_code == 0 and json.loads(res.stdout)[0]["export_spec_from_store"] is False


def test_export_leak_hit_and_sha_mismatch(store, rdir, tmp_path):
    bl = rdir / "blocklist.jsonl"
    rows = [json.dumps({"k": "formula", "v": canonical(s)}) for s in ("v", "v+a", "a_{v}+v", "b+v+c", "v-d", "e*v", "v+f", "2v+g", "h+v")]
    bl.write_text("\n".join(rows) + "\n")
    leaky = _recipe(rdir, "l.yaml", sha=_sha(bl))
    res = _run("export", store, tmp_path / "o", "--recipe", leaky)
    print(res.stdout, res.stderr, res.exception)
    assert res.exit_code == 1 and res.stdout.startswith("leak ") and not (tmp_path / "o").exists()
    res = _run("export", store, tmp_path / "o", "--recipe", leaky, "--json")
    assert res.exit_code == 1 and json.loads(res.stdout)[0]["reason"]
    bad = _recipe(rdir, "b.yaml", sha="0" * 64)
    res = _run("export", store, tmp_path / "o", "--recipe", bad)
    assert res.exit_code == 1 and str(bl) in res.stderr and "0" * 64 in res.stderr


def test_blocklist_command(tmp_path, monkeypatch):
    from glyphforge.export import leak

    monkeypatch.setattr(leak, "build_blocklist", lambda root, out: {"sha256": "ab", "counts": {"formulas": 3, "papers": 2}})
    res = _run("blocklist", tmp_path, tmp_path / "bl.jsonl")
    assert res.exit_code == 0 and "sha256 ab" in res.stdout and "formulas 3" in res.stdout and "papers 2" in res.stdout


def test_plan_prints_and_writes_nothing(rdir, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("render_many called")

    monkeypatch.setattr(pipeline, "render_many", boom)
    r = _recipe(rdir)
    before = set(tmp_path.rglob("*"))
    res = _run("plan", r)
    assert res.exit_code == 0, res.stderr
    assert "recipe_sha256" in res.stdout and "greek.upsilon_v" in res.stdout and "estimate" in res.stdout and "render_jobs" in res.stdout
    assert set(tmp_path.rglob("*")) == before
    j = _run("plan", r, "--json")
    assert json.loads(j.stdout) == pipeline.plan_run(r)


def test_validate(rdir, tmp_path, store):
    r = _recipe(rdir)
    res = _run("validate", r, "--schema", tmp_path / "s.json")
    assert res.exit_code == 0 and res.stdout.startswith("ok")
    assert (tmp_path / "s.json").read_bytes() == SCHEMA.read_bytes()
    assert _run("validate", r, "--json").exit_code == 0
    assert _run("validate", r, "--store", store).exit_code == 0
    (store / "images").rename(tmp_path / "gone")
    bad = _run("validate", r, "--store", store)
    assert bad.exit_code == 1 and "missing or corrupt" in bad.stderr


def test_validate_errors(rdir):
    bad = rdir / "bad.yaml"
    bad.write_text(yaml.safe_dump({"export": {"blocklist": {"path": "x.jsonl"}}}))
    res = _run("validate", bad)
    assert res.exit_code == 2 and "export.blocklist.sha256" in res.stderr
    assert _run("validate", _recipe(rdir, "c.yaml", classes=["greek.nope"])).exit_code == 2
    assert _run("validate", _recipe(rdir, "m.yaml", sha="0" * 64)).exit_code == 1


def test_preview_store_and_recipe(store, rdir, tmp_path):
    res = _run("preview", store, tmp_path / "p.html", "--pairs", "2")
    assert res.exit_code == 0 and str(tmp_path / "p.html") in res.stdout
    assert "<img" in (tmp_path / "p.html").read_text()
    res = _run("preview", _recipe(rdir), tmp_path / "q.html", "--pairs", "2", "--cache", tmp_path / "c2")
    assert res.exit_code == 0 and (tmp_path / "q.html").read_text().startswith("<!doctype html>")


def test_no_recipe_override_flags():
    for cmd in ("run", "plan", "export", "preview"):
        out = _run(cmd, "--help").stdout
        for flag in ("--force", "--seed", "--total", "--set"):
            assert flag not in out
