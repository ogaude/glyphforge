import os
import shutil
import subprocess
import time
import uuid

import pytest

from glyphforge.render import docker

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

HEAD = "\\documentclass{article}\n\\begin{document}\n"


def _run(tmp_path, body, timeout_s=60):
    workdir, err, timed_out = docker._run_batch([], tmp_path / "work", timeout_s, source=HEAD + body + "\n\\end{document}\n")
    log = (workdir / "batch.log").read_text(errors="replace") if workdir else ""
    return workdir, err, timed_out, log


def _argv(tmp_path, cmd):
    workdir = tmp_path / "argv"
    workdir.mkdir()
    argv = docker._docker_cmd(f"glyphforge-render-{uuid.uuid4().hex}", workdir)
    return argv[: argv.index(docker.IMAGE) + 1] + cmd


def _containers():
    return subprocess.run(["docker", "ps", "--filter", "name=glyphforge-render-", "--format", "{{.Names}}"], capture_output=True, text=True, check=True).stdout.strip()


def test_host_file_invisible(tmp_path):
    marker = f"CANARY-{uuid.uuid4().hex}"
    canary = tmp_path / "canary.txt"
    canary.write_text(marker + "\n")
    workdir, _, _, log = _run(tmp_path, f"\\IfFileExists{{{canary}}}{{\\typeout{{GF:visible}}}}{{\\typeout{{GF:hidden}}}}x")
    try:
        assert "GF:hidden" in log
        assert "GF:visible" not in log
        assert marker not in log
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def test_shell_escape_runs_nothing(tmp_path):
    workdir, err, _, log = _run(tmp_path, "\\immediate\\write18{touch /work/pwned}x")
    try:
        assert workdir is not None, err
        assert not (workdir / "pwned").exists()
        assert "runsystem(touch /work/pwned)...executed" not in log
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def test_absolute_write_refused(tmp_path):
    host = "/tmp/gf.txt"
    existed = os.path.exists(host)
    _, err, _, _ = _run(tmp_path, "\\immediate\\openout5=/tmp/gf.txt \\immediate\\write5{x}x")
    assert "I can't write on file" in err
    assert os.path.exists(host) == existed


def test_infinite_loop_killed(tmp_path):
    start = time.monotonic()
    res = docker._run_batch([], tmp_path / "work", 5, source=HEAD + "\\def\\a{\\a}\\a\n\\end{document}\n")
    assert res == (None, "timeout", True)
    assert time.monotonic() - start < 25
    assert _containers() == ""


def test_only_loopback(tmp_path):
    out = subprocess.run(_argv(tmp_path, ["cat", "/proc/net/dev"]), capture_output=True, text=True, timeout=120, check=True).stdout
    ifaces = [line.split(":")[0].strip() for line in out.splitlines()[2:] if ":" in line]
    assert ifaces == ["lo"]


def test_read_only_root(tmp_path):
    out = subprocess.run(_argv(tmp_path, ["sh", "-c", "touch /etc/gf 2>&1; echo rc=$?"]), capture_output=True, text=True, timeout=120, check=False).stdout
    assert "rc=0" not in out and "rc=" in out
