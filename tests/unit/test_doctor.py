import subprocess
import sys

import pytest

from glyphforge import cli
from glyphforge.render import docker, doctor


@pytest.fixture
def calls(monkeypatch):
    rec: list[list[str]] = []
    state = {"info": 0, "inspect": 0}

    def fake_run(argv, **kw):
        rec.append(list(argv))
        rc = state["info"] if argv[:2] == ["docker", "info"] else state["inspect"] if argv[:3] == ["docker", "image", "inspect"] else 0
        return subprocess.CompletedProcess(argv, rc, b"", b"")

    monkeypatch.setattr(docker.subprocess, "run", fake_run)
    return rec, state


def _fake_batch(monkeypatch, tmp_path, log):
    def fake(latexes, work_root, timeout_s, wrapper="display", *, preamble=None, source=None):
        d = tmp_path / "wd"
        d.mkdir(exist_ok=True)
        (d / "batch.log").write_text(log)
        return d, "", False

    monkeypatch.setattr(docker, "_run_batch", fake)


def test_docker_down_skips_probe_and_never_pulls(calls, tmp_path):
    calls, state = calls
    state["info"] = 1
    res = {c.name: c for c in doctor.run_checks(cache=tmp_path)}
    assert not res["docker"].ok and not res["image"].ok
    assert not res["probe"].ok and "skipped" in res["probe"].detail
    assert not any(c[:2] == ["docker", "pull"] for c in calls)


def test_pull_only_when_requested(calls, tmp_path, monkeypatch):
    calls, _ = calls
    _fake_batch(monkeypatch, tmp_path, "")
    doctor.run_checks(cache=tmp_path)
    assert not any(c[:2] == ["docker", "pull"] for c in calls)
    doctor.run_checks(pull=True, cache=tmp_path)
    assert [c for c in calls if c[:2] == ["docker", "pull"]] == [["docker", "pull", docker.IMAGE]]


def test_probe_parsing(calls, tmp_path, monkeypatch):
    calls, _ = calls
    def oks(skip):
        return "".join(f"GF:ok:{f}\n" for f in (*doctor.PROBE_FILES, "mathscr") if f != skip)

    _fake_batch(monkeypatch, tmp_path, oks("stix2.sty") + "GF:missing:stix2.sty\n")
    probe = {c.name: c for c in doctor.run_checks(cache=tmp_path)}["probe"]
    assert not probe.ok and "stix2.sty" in probe.detail
    _fake_batch(monkeypatch, tmp_path, oks("lgrmath.sty") + "GF:missing:lgrmath.sty\n")
    probe = {c.name: c for c in doctor.run_checks(cache=tmp_path)}["probe"]
    assert probe.ok and "lgrmath" in probe.detail


def test_cache_not_writable(calls, tmp_path):
    _, state = calls
    state["info"] = 1
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        cache = {c.name: c for c in doctor.run_checks(cache=ro)}["cache"]
    finally:
        ro.chmod(0o700)
    if not cache.ok:
        assert "not writable" in cache.detail
    else:
        pytest.skip("running as a user that ignores directory permissions")


def test_cli_hint_without_typer(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "typer", None)
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 2
    assert "glyphforge[cli]" in capsys.readouterr().err
