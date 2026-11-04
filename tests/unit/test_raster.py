import hashlib

import numpy as np

from glyphforge.render import raster


def test_constants():
    assert raster.RENDER_DPI == 300
    assert raster.INK_THRESHOLD == 250
    assert raster.TOLERANCE_VERSION == "2"


def test_bitmap_hash():
    assert raster._bitmap_hash(np.zeros((2, 3), np.uint8)) == hashlib.sha256(b"2x3:" + bytes(6)).hexdigest()


def test_ink_crop():
    a = np.full((100, 100), 255, dtype=np.uint8)
    a[30:40, 50:70] = 0
    c = raster.ink_crop(a)
    assert c.shape == (10, 20) and int(c.max()) == 0
    assert raster.ink_crop(np.full((10, 10), 255, dtype=np.uint8)) is None


def test_overflow_margin():
    a = np.full((100, 100), 255, dtype=np.uint8)
    a[40:50, 2:30] = 0
    assert raster.ink_overflows(a)
    b = np.full((100, 100), 255, dtype=np.uint8)
    b[40:50, 40:60] = 0
    assert not raster.ink_overflows(b)


def _page():
    a = np.full((120, 800), 255, dtype=np.uint8)
    for x in range(20, 780, 60):
        a[30:80, x : x + 14] = 0
    return a


def test_compare_arrays():
    a = np.full((100, 100), 255, dtype=np.uint8)
    assert raster.compare_arrays(a, a.copy()) == (True, True)
    b = a.copy()
    b[5, 5] = 55
    assert raster.compare_arrays(a, b) == (False, True)
    d = np.full((100, 104), 255, dtype=np.uint8)
    assert raster.compare_arrays(a, d) == (False, False)
    assert raster.compare_arrays(a, None) == (False, False)
    assert raster.compare_arrays(None, a) == (False, False)


def test_compare_arrays_long_equation():
    a = _page()
    one = a.copy()
    one[5, 5] = 55
    assert raster.compare_arrays(a, one) == (False, True)
    block = a.copy()
    block[100:112, 400:408] = 0
    assert raster.compare_arrays(a, block) == (False, False)
    s1 = np.full((60, 60), 255, dtype=np.uint8)
    s1[10:40, 20:22] = 0
    s2 = s1.copy()
    s2[10:40, 22] = 0
    assert raster.compare_arrays(s1, s2) == (False, False)
    wider = np.concatenate([a, np.full((120, 1), 255, dtype=np.uint8)], axis=1)
    assert raster.compare_arrays(a, wider) == (False, True)
    shifted = np.full((121, 801), 255, dtype=np.uint8)
    shifted[1:, 1:] = a
    assert raster.compare_arrays(a, shifted) == (False, True)
