import hashlib

import pytest

from glyphforge.canon import safety
from glyphforge.render import batch, cache, docker, raster


def test_default_cache_key_payload_unchanged():
    payload = (
        docker.IMAGE_DIGEST + "\n" + docker.PREAMBLE_SHA256 + "\n" + safety.WRAP_VERSION + "\n" + safety.FILTER_VERSION
        + "\n" + str(raster.RENDER_DPI) + "\n" + "x+1"
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert cache.cache_key("x+1") == expected
    assert cache.cache_key("x+1", wrapper="display") == expected


def test_env_cache_key_differs():
    env = r"\begin{align*}a\end{align*}"
    assert cache.cache_key(env, wrapper="env") != cache.cache_key(env)


def test_versions():
    assert safety.WRAP_VERSION == "1"
    assert safety.FILTER_VERSION == "3"


def test_batch_source_env_is_verbatim():
    env = "\\begin{align*}a&=b\\\\c&=d\\end{align*}"
    src = docker._batch_source([f"  {env}\n"], wrapper="env")
    assert env + "\n\\newpage\n" in src
    assert "\\[" not in src
    assert src == docker._batch_source([env], wrapper="env")


def test_batch_source_default_unchanged():
    src = docker._batch_source(["x+1"])
    assert src.endswith("\\begin{document}\n" + safety.wrap("x+1") + "\n\\newpage\n\\end{document}\n")


def test_env_wrapper_rejects_without_docker(tmp_path, monkeypatch):
    def boom():
        raise AssertionError("docker must not be consulted")

    monkeypatch.setattr(docker, "docker_available", boom)
    items = ["x+1", r"\begin{align}a\end{align}", r"\begin{equation*}x\end{align*}", r"\begin{multline*}x\end{multline*}"]
    for r in batch.render_many(items, cache=tmp_path, wrapper="env"):
        assert r.status == "rejected"
        assert r.note == "not a starred display env"


def test_env_wrapper_still_runs_check_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(docker, "docker_available", lambda: (_ for _ in ()).throw(AssertionError("no docker")))
    (r,) = batch.render_many([r"\begin{equation*}\def\x{1}\end{equation*}"], cache=tmp_path, wrapper="env")
    assert r.status == "rejected" and "forbidden primitive" in r.note


def test_unknown_wrapper_raises(tmp_path):
    with pytest.raises(ValueError):
        batch.render_many(["x"], cache=tmp_path, wrapper="nope")


@pytest.mark.docker
def test_env_wrapper_renders(tmp_path):
    (r,) = batch.render_many(["\\begin{align*}a&=b\\\\c&=d\\end{align*}"], cache=tmp_path, wrapper="env")
    assert r.status == "rendered"
