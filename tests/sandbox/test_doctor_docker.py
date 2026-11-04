import importlib.util
import subprocess
import sys

import pytest

from glyphforge.render import docker, doctor

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]


def test_run_checks_all_ok(tmp_path):
    checks = doctor.run_checks(cache=tmp_path)
    assert [c.name for c in checks] == ["docker", "image", "probe", "memory", "cache"]
    assert all(c.ok for c in checks), checks
    assert "missing" not in checks[2].detail


@pytest.mark.skipif(importlib.util.find_spec("typer") is None, reason="typer not installed")
def test_cli_doctor():
    code = "import sys; sys.argv = ['glyphforge', 'doctor']; from glyphforge.cli import main; main()"
    r = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "probe" in r.stdout


def test_module_entry_point():
    r = subprocess.run([sys.executable, "-m", "glyphforge.render.doctor"], check=False, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
