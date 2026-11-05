"""Static invariants of the CI and release workflows (security-relevant wiring)."""

import re
from pathlib import Path

import pytest
import yaml

DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
NAMES = ("ci", "docker-tests", "release")


def _load(name: str) -> dict:
    return yaml.safe_load((DIR / f"{name}.yml").read_text())


def _on(wf: dict) -> dict:
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


def _needs(job: dict) -> list[str]:
    n = job.get("needs", [])
    return [n] if isinstance(n, str) else list(n)


def test_triggers():
    ci, dk, rel = (_on(_load(n)) for n in NAMES)
    assert "branches" in ci["push"] and "tags" not in ci["push"]
    assert {"workflow_call", "schedule", "workflow_dispatch"} <= set(dk)
    assert rel["push"] == {"tags": ["v*"]} and "workflow_dispatch" in rel


def test_oidc_scope():
    for n in NAMES:
        assert "id-token" not in (_load(n).get("permissions") or {})
    jobs = _load("release")["jobs"]
    holders = {k for k, j in jobs.items() if (j.get("permissions") or {}).get("id-token") == "write"}
    assert holders == {"publish-testpypi", "publish-pypi"}
    for k in holders:
        assert any(s.get("uses", "").startswith("pypa/gh-action-pypi-publish@") for s in jobs[k]["steps"])


def test_environments():
    jobs = _load("release")["jobs"]
    assert jobs["publish-testpypi"]["environment"] == "testpypi"
    step = next(s for s in jobs["publish-testpypi"]["steps"] if "pypi-publish" in s.get("uses", ""))
    assert step["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    assert jobs["publish-pypi"]["environment"] == "pypi"


def test_ordering():
    jobs = _load("release")["jobs"]
    assert jobs["docker"]["uses"] == "./.github/workflows/docker-tests.yml"
    assert {"build", "docker"} <= set(_needs(jobs["publish-testpypi"]))
    assert _needs(jobs["smoke-testpypi"]) == ["publish-testpypi"]
    assert _needs(jobs["publish-pypi"]) == ["smoke-testpypi"]
    gr = _needs(jobs["github-release"])
    assert {"build", "docker"} <= set(gr) and not {"publish-testpypi", "smoke-testpypi", "publish-pypi"} & set(gr)


def test_pypi_gate():
    jobs = _load("release")["jobs"]
    assert jobs["publish-testpypi"]["if"] == "vars.PUBLISH_PYPI == 'true'"
    for k in ("smoke-testpypi", "publish-pypi"):
        assert "if" not in jobs[k]
    assert jobs["github-release"]["if"] == "github.event_name == 'push'"


@pytest.mark.parametrize("name", NAMES)
def test_no_secrets(name):
    text = (DIR / f"{name}.yml").read_text()
    assert not re.search(r"^\s*password:", text, re.MULTILINE)
    assert set(re.findall(r"secrets\.(\w+)", text)) <= {"GITHUB_TOKEN"}


@pytest.mark.parametrize("name", NAMES)
def test_pinned(name):
    uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", (DIR / f"{name}.yml").read_text(), re.MULTILINE)
    assert uses
    for u in uses:
        assert u.startswith("./") or re.search(r"@[0-9a-f]{40}$", u), u
