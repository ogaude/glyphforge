from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from glyphforge.render import cache

KEY = "ab" + "0" * 62


def _res(key=KEY):
    return cache.RenderResult(key, "rendered", (2, 3), "h")


def test_concurrent_same_key_no_collision(tmp_path):
    bm = np.zeros((2, 3), dtype=np.uint8)
    with ThreadPoolExecutor(8) as ex:
        for f in [ex.submit(cache._cache_put, tmp_path, _res(), bm) for _ in range(8 * 25)]:
            f.result()
    got = cache._cache_get(tmp_path, KEY)
    assert got == _res()
    assert cache.load_bitmap(got, tmp_path).shape == (2, 3)
    assert not list((tmp_path / "render").rglob("*.tmp"))


def test_two_keys_concurrent(tmp_path):
    keys = [KEY, "cd" + "1" * 62]
    bm = np.ones((2, 3), dtype=np.uint8)
    with ThreadPoolExecutor(4) as ex:
        for f in [ex.submit(cache._cache_put, tmp_path, _res(k), bm) for k in keys * 20]:
            f.result()
    for k in keys:
        assert cache._cache_get(tmp_path, k) == _res(k)
        assert cache.load_bitmap(_res(k), tmp_path).shape == (2, 3)


def test_failed_write_leaves_no_temp(tmp_path, monkeypatch):
    def boom(fh, arr):
        raise RuntimeError("disk")

    monkeypatch.setattr(cache.np, "save", boom)
    with pytest.raises(RuntimeError):
        cache._cache_put(tmp_path, _res(), np.zeros((2, 3), dtype=np.uint8))
    assert not list((tmp_path / "render").rglob("*.tmp"))
