import os
import subprocess
from pathlib import Path

import pytest

from glyphforge import resources
from glyphforge.render import docker

GM_ROOT = Path(os.environ.get("GLYPHFORGE_GLYPHFIX_ROOT") or Path(__file__).resolve().parents[3] / "glyphfix-math")
GM_PREAMBLE = GM_ROOT / "src/glyphfix_math/preamble.tex"
DIGEST = "sha256:0f4884ca7d287f47ab466d2dd405d4c901c576585363f628863a7ca7eea21301"


def test_preamble_sha():
    assert docker.PREAMBLE_SHA256 == "65f94732462b53dee104e2f8d1828eea267d3e9abfbbdd082f4796426bb00717"


def test_preamble_matches_glyphfix_math():
    if not GM_PREAMBLE.exists():
        pytest.skip("sibling glyphfix-math checkout not present")
    assert GM_PREAMBLE.read_bytes() == docker.PREAMBLE.encode("utf-8")


def test_image_pinned():
    assert docker.IMAGE == f"texlive/texlive@{DIGEST}"


def test_docker_cmd_literal():
    assert docker._docker_cmd("n", Path("/w")) == [
        "docker", "run", "--rm", "--name", "n",
        "--network", "none",
        "--memory", "4g", "--memory-swap", "4g",
        "--cpus", "2", "--pids-limit", "512",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=256m",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp", "-e", "TEXMFVAR=/tmp/texmf-var",
        "-v", "/w:/work", "-w", "/work",
        f"texlive/texlive@{DIGEST}",
        "pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "batch.tex",
    ]  # fmt: skip


def test_batch_source_preamble():
    assert docker._batch_source(["x"]).startswith(docker.PREAMBLE + "\\begin{document}\n")
    assert docker._batch_source(["x"], preamble="P").startswith("P\\begin{document}\n")


def test_timeout_kills_container(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: 1 << 50)
    calls, kws = [], []

    def run(cmd, **kw):
        calls.append(cmd)
        kws.append(kw)
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(docker.subprocess, "run", run)
    assert docker._run_batch(["x"], tmp_path, 1) == (None, "timeout", True)
    assert calls[1][:2] == ["docker", "kill"] and calls[1][2].startswith("glyphforge-render-")
    assert kws[1].get("timeout")
    assert calls[2][:3] == ["docker", "ps", "-q"]
    assert calls[1][2] == calls[0][calls[0].index("--name") + 1]
    assert list(tmp_path.iterdir()) == []


def test_source_override_written_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: 1 << 50)
    seen = {}

    def run(cmd, **kw):
        if cmd[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        seen["tex"] = next(tmp_path.iterdir()).joinpath("batch.tex").read_text()
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(docker.subprocess, "run", run)
    docker._run_batch(["x"], tmp_path, 1, source="RAW")
    assert seen["tex"] == "RAW"


def test_unconfirmed_kill_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: 1 << 50)

    def run(cmd, **kw):
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(docker.subprocess, "run", run)
    with pytest.raises(docker.RenderInfrastructureError, match="glyphforge-render-"):
        docker._run_batch(["x"], tmp_path, 1)
    assert list(tmp_path.iterdir()) == []
