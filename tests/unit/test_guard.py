import os
import subprocess
import sys
import time

import pytest

from glyphforge import resources as G
from glyphforge.resources import GIB, Sampler


def fake(mem=100 * GIB):
    return Sampler(mem=lambda: mem() if callable(mem) else mem)


def test_mem_available(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:  9999999 kB\nMemAvailable:   2048000 kB\n")
    assert G.mem_available_bytes(str(p)) == 2048000 * 1024


def test_mem_available_missing(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal: 1 kB\n")
    with pytest.raises(G.GuardUnmeasurable):
        G.mem_available_bytes(str(p))


def test_defaults():
    assert G.RAM_FLOOR_BYTES == 1610612736
    assert (G.DOCKER_MEMORY, G.DOCKER_MEMORY_GB, G.DOCKER_MAX_PARALLEL) == ("4g", 4, 3)


def test_preflight_ram_timeout():
    with pytest.raises(G.GuardTimeout) as ei:
        G.preflight(ram_gb=4, timeout_s=0.3, poll_s=0.1, sampler=fake(mem=3 * GIB), log=lambda m: None)
    assert ei.value.exit_code == 75
    assert "MemAvailable" in str(ei.value)
    assert "3.0 GiB" in str(ei.value) and "5.5 GiB" in str(ei.value)


def test_preflight_workers_need():
    with pytest.raises(G.GuardTimeout):
        G.preflight(ram_gb=4, workers=2, timeout_s=0.1, poll_s=0.05, sampler=fake(mem=int(9.4 * GIB)), log=lambda m: None)
    G.preflight(ram_gb=4, workers=2, sampler=fake(mem=int(9.6 * GIB)))


def test_preflight_ok_and_waits_until_sufficient():
    G.preflight(ram_gb=1, sampler=fake())
    calls = {"n": 0}

    def mem():
        calls["n"] += 1
        return 10 * GIB if calls["n"] >= 3 else 1 * GIB

    G.preflight(ram_gb=2, poll_s=0.01, timeout_s=5, sampler=fake(mem=mem), log=lambda m: None)
    assert calls["n"] == 3


@pytest.mark.parametrize(("mem_gib", "expected"), [(9, 1), (20, 3), (5, 0), (1, 0), (5.6, 1), (5.4, 0)])
def test_docker_parallel_cap(mem_gib, expected):
    assert G.docker_parallel_cap(sampler=fake(mem=int(mem_gib * GIB)), per_container_gb=4) == expected


def _timed_mem(t0, low_from, low_until):
    def mem():
        t = time.monotonic() - t0
        return 0 if low_from <= t < low_until else 100 * GIB

    return mem


def _state(pid):
    with open(f"/proc/{pid}/stat") as fh:
        return fh.read().rsplit(")", 1)[1].split()[0]


def test_guard_pause_resume():
    t0 = time.monotonic()
    s = fake(mem=_timed_mem(t0 + 0.1, 0.0, 0.9))
    proc = subprocess.Popen(["sleep", "1.5"], start_new_session=True)
    try:
        with G.guard(ram_gb=0.1, watch_s=0.05, grace_s=5, sampler=s) as g:
            g.register_child(proc)
            time.sleep(0.5)
            assert g.paused and _state(proc.pid) == "T"
            g.wait_if_paused(timeout_s=3)
            assert not g.paused
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_guard_abort_terminates_child():
    t0 = time.monotonic()
    s = fake(mem=_timed_mem(t0 + 0.1, 0.0, 1e9))
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    start = time.monotonic()
    try:
        with pytest.raises(G.GuardAbort) as ei, G.guard(ram_gb=0.1, watch_s=0.05, grace_s=0.3, sampler=s) as g:
            g.register_child(proc)
            deadline = time.monotonic() + 5
            seen_paused = False
            while time.monotonic() < deadline and not g.aborted:
                seen_paused = seen_paused or g.paused
                time.sleep(0.02)
            assert seen_paused
            g.check()
        assert ei.value.exit_code == 76
        assert proc.wait(timeout=8) != 0
        assert time.monotonic() - start < 8
    finally:
        if proc.poll() is None:
            proc.kill()


def _import(env):
    return subprocess.run(
        [sys.executable, "-I", "-c", "from glyphforge import resources as r; print(r.DOCKER_MEMORY, r.DOCKER_MAX_PARALLEL)"],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
    )


def test_env_overrides():
    r = _import({"GLYPHFORGE_DOCKER_MEMORY_GB": "2", "GLYPHFORGE_MAX_WORKERS": "5"})
    assert r.stdout.split() == ["2g", "5"]
    r = _import({"GLYPHFORGE_MAX_WORKERS": "0"})
    assert r.returncode != 0 and "ValueError" in r.stderr
