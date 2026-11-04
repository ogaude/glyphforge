import json
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from glyphforge import resources
from glyphforge.render import batch, cache, docker, raster
from glyphforge.render.style import Style


@pytest.fixture(autouse=True)
def _no_preflight(monkeypatch):
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: 1 << 50)
    # Scenario fakes only understand `docker run`; the memory reservation has its own tests below.
    monkeypatch.setattr(docker, "docker_available", lambda: True)


def _workdir(argv):
    return Path(argv[argv.index("-v") + 1].split(":/work")[0])


class Fake:
    """Stand-in for `docker run`: scenario picks the outcome from the argv and batch.tex."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, argv, *a, **k):
        if argv[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        with self._lock:
            self.calls += 1
        return self.scenario(argv, _workdir(argv))


def healthy(argv, wd):
    (wd / "batch.log").write_text("This is pdfTeX\nOutput written\n")
    (wd / "batch.pdf").write_bytes(b"%PDF")
    return subprocess.CompletedProcess(argv, 0, "", "")


def outage(argv, wd):
    return subprocess.CompletedProcess(argv, 125, "", "docker: Cannot connect to the Docker daemon")


def _pages(monkeypatch):
    def fake(workdir, expected):
        page = np.full((200, 200), 255, dtype=np.uint8)
        page[90:110, 80:110] = 0
        return [page.copy() for _ in range(expected)]

    monkeypatch.setattr(raster, "_rasterize", fake)


def _jsons(tmp_path):
    return list((tmp_path / "render").rglob("*.json")) if (tmp_path / "render").exists() else []


def _install(monkeypatch, scenario):
    f = Fake(scenario)
    monkeypatch.setattr(docker.subprocess, "run", f)
    return f


def test_outage_raises_once_and_caches_nothing(tmp_path, monkeypatch):
    f = _install(monkeypatch, outage)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many(["a", "b", "c", "d"], cache=tmp_path, max_parallel=1)
    assert f.calls == 1
    assert _jsons(tmp_path) == []


@pytest.mark.parametrize("code", sorted(docker.INFRA_EXIT_CODES))
def test_infra_exit_codes_raise_even_with_error_log(tmp_path, monkeypatch, code):
    def scenario(argv, wd):
        (wd / "batch.log").write_text("! Emergency stop.\n")
        return subprocess.CompletedProcess(argv, code, "", "boom")

    _install(monkeypatch, scenario)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    assert _jsons(tmp_path) == []


def test_unexplained_nonzero_exit_raises(tmp_path, monkeypatch):
    def scenario(argv, wd):
        (wd / "batch.log").write_text("no errors here\n")
        return subprocess.CompletedProcess(argv, 1, "", "")

    _install(monkeypatch, scenario)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    assert _jsons(tmp_path) == []


def test_missing_pdf_raises(tmp_path, monkeypatch):
    def scenario(argv, wd):
        (wd / "batch.log").write_text("fine\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    _install(monkeypatch, scenario)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many(["a"], cache=tmp_path, max_parallel=1)
    assert _jsons(tmp_path) == []


def test_ground_truth_not_dropped_after_outage(tmp_path, monkeypatch):
    _install(monkeypatch, outage)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_equivalence(["x", "y"], ["x", "z"], cache=tmp_path, max_parallel=1)
    _install(monkeypatch, healthy)
    _pages(monkeypatch)
    rows = batch.render_equivalence(["x", "y"], ["x", "z"], cache=tmp_path, max_parallel=1)
    assert [r.gt_status for r in rows] == ["rendered", "rendered"]
    assert all(r.identical is not None for r in rows)


def test_latex_error_is_cached_with_bang_note(tmp_path, monkeypatch):
    def scenario(argv, wd):
        if "\\undefinedcmd" in (wd / "batch.tex").read_text():
            (wd / "batch.log").write_text("! Undefined control sequence.\n")
            return subprocess.CompletedProcess(argv, 1, "", "")
        return healthy(argv, wd)

    _install(monkeypatch, scenario)
    _pages(monkeypatch)
    eqs = ["a", "b", r"\undefinedcmd{c}", "d"]
    res = batch.render_many(eqs, batch_size=8, cache=tmp_path, max_parallel=1)
    assert [r.status for r in res] == ["rendered", "rendered", "compile-failed", "rendered"]
    d = json.loads(cache._entry(tmp_path, cache.cache_key(eqs[2]), ".json").read_text())
    assert d["status"] == "compile-failed" and d["note"].startswith("!")


def test_timeout_returned_but_not_cached(tmp_path, monkeypatch):
    def run(argv, *a, **k):
        if argv[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(docker.subprocess, "run", run)
    (res,) = batch.render_many(["a"], cache=tmp_path, max_parallel=1)
    assert res.status == "timeout"
    assert not cache._entry(tmp_path, cache.cache_key("a"), ".json").exists()
    _install(monkeypatch, healthy)
    _pages(monkeypatch)
    (res,) = batch.render_many(["a"], cache=tmp_path, max_parallel=1)
    assert res.status == "rendered"


def test_legacy_entries_are_cache_misses(tmp_path):
    key = cache.cache_key("a")
    p = cache._entry(tmp_path, key, ".json")
    p.parent.mkdir(parents=True)
    base = {"shape": None, "bitmap_sha256": None}
    p.write_text(json.dumps({**base, "status": "compile-failed", "note": "pdflatex exit 125"}))
    assert cache._cache_get(tmp_path, key) is None
    p.write_text(json.dumps({**base, "status": "timeout", "note": "timeout"}))
    assert cache._cache_get(tmp_path, key) is None
    p.write_text(json.dumps({**base, "status": "compile-failed", "note": "! Undefined control sequence."}))
    got = cache._cache_get(tmp_path, key)
    assert got is not None and got.status == "compile-failed"


def test_abort_flag_set_blocks_container(tmp_path, monkeypatch):
    f = _install(monkeypatch, healthy)
    ev = threading.Event()
    ev.set()
    with pytest.raises(docker.RenderInfrastructureError):
        batch._render_group([(cache.cache_key("a"), "a")], tmp_path / "work", 30, tmp_path, abort=ev)
    assert f.calls == 0


def test_abort_flag_set_on_failure(tmp_path, monkeypatch):
    _install(monkeypatch, outage)
    ev = threading.Event()
    items = [(cache.cache_key("a"), "a"), (cache.cache_key("b"), "b")]
    with pytest.raises(docker.RenderInfrastructureError):
        batch._render_group(items, tmp_path / "work", 30, tmp_path, abort=ev)
    assert ev.is_set()


def test_parallel_abort_bounds_container_calls(tmp_path, monkeypatch):
    f = _install(monkeypatch, outage)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many([f"e{i}" for i in range(8)], batch_size=2, cache=tmp_path, max_parallel=2)
    assert f.calls <= 2
    assert _jsons(tmp_path) == []


def test_unavailable_docker_raises_before_any_container(tmp_path, monkeypatch):
    f = _install(monkeypatch, healthy)
    monkeypatch.setattr(docker, "docker_available", lambda: False)
    monkeypatch.setattr(docker, "docker_diagnosis", lambda: "docker daemon unreachable")
    with pytest.raises(docker.RenderInfrastructureError, match="not available.*unreachable"):
        batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    assert f.calls == 0
    assert _jsons(tmp_path) == []


def test_fully_cached_run_needs_no_docker(tmp_path, monkeypatch):
    _pages(monkeypatch)
    _install(monkeypatch, healthy)
    first = batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    monkeypatch.setattr(docker, "docker_available", lambda: False)
    f = _install(monkeypatch, outage)
    second = batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    assert [r.key for r in second] == [r.key for r in first]
    assert f.calls == 0


def test_docker_available_false_on_hung_daemon(monkeypatch):
    def hang(*a, **k):
        raise subprocess.TimeoutExpired("docker", 20)

    monkeypatch.undo()
    monkeypatch.setattr(docker.subprocess, "run", hang)
    assert docker.docker_available() is False


def test_docker_diagnosis_distinguishes_daemon_from_image(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(docker.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, b"", b""))
    assert "unreachable" in docker.docker_diagnosis()
    monkeypatch.setattr(docker.subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, b"", b""))
    assert "docker pull" in docker.docker_diagnosis()


def test_oserror_becomes_infra_error_sets_abort_and_leaks_no_workdir(tmp_path, monkeypatch):
    def run(argv, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(docker.subprocess, "run", run)
    ev = threading.Event()
    with pytest.raises(docker.RenderInfrastructureError, match="PermissionError"):
        batch._render_group([(cache.cache_key("a"), "a")], tmp_path / "work", 30, tmp_path, abort=ev)
    assert ev.is_set()
    assert list((tmp_path / "work").glob("batch-*")) == []


def test_real_error_not_masked_by_aborted_sibling(tmp_path, monkeypatch):
    # first group hits the abort flag (raised as "aborted"), a later group holds the real failure
    _install(monkeypatch, outage)
    real = docker.RenderInfrastructureError("real docker failure (exit 125)")
    second_started = threading.Event()

    def fake_inner(items, *a, abort=None, errors=None, **k):
        if items[0][1] == "a":
            second_started.wait(5)
            raise batch._AbortedError("aborted: x")
        second_started.set()
        raise real

    monkeypatch.setattr(batch, "_render_group_inner", fake_inner)
    with pytest.raises(docker.RenderInfrastructureError, match="real docker failure"):
        batch.render_many(["a", "b"], batch_size=1, cache=tmp_path, max_parallel=2)


def test_reservation_releases_lock_while_waiting(tmp_path, monkeypatch):
    need_one = int(resources.DOCKER_MEMORY_GB * resources.GIB) + resources.RAM_FLOOR_BYTES
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: need_one)
    monkeypatch.setattr(docker, "_RESERVE_POLL_S", 0.05)
    monkeypatch.setattr(docker, "_RESERVE_TIMEOUT_S", 5)
    _install(monkeypatch, healthy)
    docker._inflight[0] = 1
    out = []
    t = threading.Thread(target=lambda: out.append(docker._run_batch(["x"], tmp_path, 5)))
    t.start()
    try:
        time.sleep(0.2)
        assert docker._START_LOCK.acquire(timeout=1)  # the waiter sleeps outside the lock
        docker._START_LOCK.release()
        assert t.is_alive() and not out
        docker._inflight[0] = 0
        t.join(5)
        assert out and out[0][0] is not None
    finally:
        docker._inflight[0] = 0
        t.join(5)
    assert docker._inflight[0] == 0


def test_reservation_timeout_is_infrastructure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(resources, "mem_available_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(docker, "_RESERVE_POLL_S", 0.05)
    monkeypatch.setattr(docker, "_RESERVE_TIMEOUT_S", 0.2)
    f = _install(monkeypatch, healthy)
    with pytest.raises(docker.RenderInfrastructureError, match="memory floor"):
        docker._run_batch(["x"], tmp_path, 5)
    assert docker._inflight[0] == 0 and f.calls == 0
    assert capsys.readouterr().out == ""


def test_unexpected_workdir_file_is_infrastructure(tmp_path, monkeypatch):
    def scenario(argv, wd):
        (wd / "pwned.txt").write_text("x")
        return healthy(argv, wd)

    _install(monkeypatch, scenario)
    with pytest.raises(docker.RenderInfrastructureError, match="pwned.txt"):
        docker._run_batch(["x"], tmp_path / "work", 5)
    assert list((tmp_path / "work").glob("batch-*")) == []


def test_aux_file_is_accepted(tmp_path, monkeypatch):
    def scenario(argv, wd):
        (wd / "batch.aux").write_text("x")
        return healthy(argv, wd)

    _install(monkeypatch, scenario)
    wd, _err, timed_out = docker._run_batch(["x"], tmp_path / "work", 5)
    assert wd is not None and not timed_out


def test_right_half_workdir_removed_when_left_half_raises(tmp_path, monkeypatch):
    def run(argv, *a, **k):
        if argv[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        wd = _workdir(argv)
        tex = (wd / "batch.tex").read_text()
        if all(f"e{i}" in tex for i in range(4)):
            raise subprocess.TimeoutExpired(argv, 1)  # whole batch
        if "e0" in tex and "e2" not in tex:
            if "e1" in tex:
                raise subprocess.TimeoutExpired(argv, 1)  # left half
            return outage(argv, wd)  # left singleton
        return healthy(argv, wd)

    monkeypatch.setattr(docker.subprocess, "run", run)
    _pages(monkeypatch)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many([f"e{i}" for i in range(4)], batch_size=4, cache=tmp_path, max_parallel=1)
    assert list((tmp_path / "work").glob("batch-*")) == []


def test_zero_cap_does_not_call_preflight(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("preflight must not be called")

    monkeypatch.setattr(resources, "preflight", boom)
    monkeypatch.setattr(resources, "docker_parallel_cap", lambda: 0)
    _install(monkeypatch, healthy)
    _pages(monkeypatch)
    (res,) = batch.render_many(["a"], cache=tmp_path)
    assert res.status == "rendered"


def test_inflight_released_on_failure(tmp_path, monkeypatch):
    _install(monkeypatch, outage)
    with pytest.raises(docker.RenderInfrastructureError):
        batch.render_many(["a"], cache=tmp_path, max_parallel=1)
    assert docker._inflight[0] == 0


def test_timeout_on_both_halves_is_infrastructure(tmp_path, monkeypatch):
    calls = []

    def run(argv, *a, **k):
        if argv[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(docker.subprocess, "run", run)
    with pytest.raises(docker.RenderInfrastructureError, match="too slow"):
        batch.render_many([f"e{i}" for i in range(16)], batch_size=16, cache=tmp_path, max_parallel=1)
    assert len(calls) == 3  # whole batch plus its two halves, no deeper bisection
    assert list((tmp_path / "work").glob("batch-*")) == []


@pytest.mark.parametrize("code", sorted(docker.KILL_EXIT_CODES))
def test_pathological_equation_killed_is_isolated_and_not_cached(tmp_path, monkeypatch, code):
    def scenario(argv, wd):
        if "BOOM" in (wd / "batch.tex").read_text():
            (wd / "batch.log").write_text("killed\n")
            return subprocess.CompletedProcess(argv, code, "", "")
        return healthy(argv, wd)

    _install(monkeypatch, scenario)
    _pages(monkeypatch)
    res = batch.render_many(["a", "BOOM", "c", "d"], batch_size=8, cache=tmp_path, max_parallel=1)
    assert [r.status for r in res] == ["rendered", "compile-failed", "rendered", "rendered"]
    assert res[1].note.startswith(docker.KILLED_NOTE)
    assert not cache._entry(tmp_path, cache.cache_key("BOOM"), ".json").exists()
    assert cache._cache_get(tmp_path, cache.cache_key("a")) is not None


def test_unloadable_page_returns_none_not_exception(tmp_path, monkeypatch):
    import pypdfium2 as pdfium

    class BadDoc:
        def __init__(self, path):
            pass

        def __len__(self):
            return 2

        def __getitem__(self, i):
            raise pdfium.PdfiumError("Failed to load page.")

        def close(self):
            pass

    monkeypatch.setattr(pdfium, "PdfDocument", BadDoc)
    assert raster._rasterize(tmp_path, 2) is None


def test_unopenable_pdf_returns_none_not_exception(tmp_path):
    (tmp_path / "batch.pdf").write_bytes(b"this is not a pdf")
    assert raster._rasterize(tmp_path, 1) is None


def test_unloadable_page_singleton_is_a_result_not_a_crash(tmp_path, monkeypatch):
    _install(monkeypatch, healthy)
    monkeypatch.setattr(raster, "_rasterize", lambda workdir, expected: None)
    res = batch.render_many(["a", "b", "c"], cache=tmp_path, max_parallel=1)
    assert [r.status for r in res] == ["compile-failed"] * 3
    assert _jsons(tmp_path) == []


def test_render_many_rejects_without_docker(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("docker must not be called")

    monkeypatch.setattr(docker.subprocess, "run", boom)
    res = batch.render_many([r"\input{/etc/passwd}", ""], cache=tmp_path)
    assert [r.status for r in res] == ["rejected", "empty"]


def _recording(texts):
    def scenario(argv, wd):
        texts.append((wd / "batch.tex").read_text())
        return healthy(argv, wd)

    return scenario


def test_batches_group_by_preamble_key(tmp_path, monkeypatch):
    texts = []
    f = _install(monkeypatch, _recording(texts))
    _pages(monkeypatch)
    newtx = Style(font="newtx")
    res = batch.render_many(["a", "b", "c"], style=[Style(), newtx, Style()], cache=tmp_path, max_parallel=1)
    assert [r.status for r in res] == ["rendered"] * 3
    assert f.calls == 2
    default = next(t for t in texts if t.startswith(docker.PREAMBLE))
    other = next(t for t in texts if t.startswith(newtx.preamble))
    assert default == docker._batch_source(["a", "c"])
    assert other == docker._batch_source(["b"], preamble=newtx.preamble)


def test_default_batch_tex_is_glyphfix_math_document(tmp_path, monkeypatch):
    texts = []
    _install(monkeypatch, _recording(texts))
    _pages(monkeypatch)
    batch.render_many(["a", "b"], cache=tmp_path, max_parallel=1)
    assert texts == [docker._batch_source(["a", "b"])]


def test_second_identical_call_hits_cache(tmp_path, monkeypatch):
    f = _install(monkeypatch, healthy)
    _pages(monkeypatch)
    batch.render_many(["a", "b"], style=Style(font="stix2"), cache=tmp_path, max_parallel=1)
    assert f.calls == 1
    batch.render_many(["a", "b"], style=Style(font="stix2"), cache=tmp_path, max_parallel=1)
    assert f.calls == 1


def test_style_sequence_length_mismatch_raises(tmp_path):
    with pytest.raises(ValueError):
        batch.render_many(["a", "b"], style=[Style()], cache=tmp_path)
