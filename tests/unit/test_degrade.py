import io
import json
import struct

import numpy as np
import pytest
from PIL import Image

from glyphforge.degrade import apply_ops, degrade_ops
from glyphforge.recipe.schema import DEGRADE_DEFAULTS, DEGRADE_OPS, DegradeSpec
from glyphforge.store import png_bytes

ALL = {op: {"p": 1.0} for op in DEGRADE_OPS}


def _png(w=60, h=40):
    arr = np.full((h, w), 255, np.uint8)
    arr[10:30, 15:45] = 0
    return png_bytes(arr)


def _chunks(png):
    out, pos = [], 8
    while pos < len(png):
        n = struct.unpack(">I", png[pos : pos + 4])[0]
        out.append(png[pos + 4 : pos + 8].decode())
        pos += 12 + n
    return out


def test_empty_when_unconfigured():
    assert degrade_ops(None, 1, "p0") == []
    assert degrade_ops(DegradeSpec(), 1, "p0") == []


def test_deterministic_and_key_sensitive():
    spec = DegradeSpec(**ALL)
    assert degrade_ops(spec, 1, "p0") == degrade_ops(spec, 1, "p0")
    assert degrade_ops(spec, 1, "p0") != degrade_ops(spec, 1, "p1")
    assert degrade_ops(spec, 1, "p0") != degrade_ops(spec, 2, "p0")


def test_order_ranges_and_json():
    spec = DegradeSpec(**ALL)
    for key in ("a", "b", "c", "d"):
        ops = degrade_ops(spec, 7, key)
        assert [o["op"] for o in ops] == list(DEGRADE_OPS)
        by = {o["op"]: o for o in ops}
        for name, field in (("contrast", "c"), ("rotate", "deg"), ("blur", "sigma"), ("noise", "sigma"), ("jpeg", "quality")):
            lo, hi = DEGRADE_DEFAULTS[name]
            assert lo <= abs(by[name][field]) <= hi
        assert isinstance(by["jpeg"]["quality"], int)
        assert isinstance(by["noise"]["seed"], int) and by["noise"]["seed"] < 2**63
        assert json.loads(json.dumps(ops)) == ops


def test_no_drift_when_one_probability_changes():
    a = DegradeSpec(**(ALL | {"blur": {"p": 0.2}}))
    b = DegradeSpec(**(ALL | {"blur": {"p": 0.9}}))
    for key in map(str, range(20)):
        da = {o["op"]: o for o in degrade_ops(a, 3, key)}
        db = {o["op"]: o for o in degrade_ops(b, 3, key)}
        for name in ("contrast", "rotate", "noise", "jpeg"):
            assert da.get(name) == db.get(name)


def test_clean_share():
    assert all(degrade_ops(DegradeSpec(clean_share=1.0, **ALL), 1, str(k)) == [] for k in range(30))
    assert all(degrade_ops(DegradeSpec(clean_share=0.0, **ALL), 1, str(k)) for k in range(30))


def test_copy_through_and_determinism():
    png = _png()
    assert apply_ops(png, []) == png
    ops = degrade_ops(DegradeSpec(**ALL), 1, "k")
    out = apply_ops(png, ops)
    assert out == apply_ops(png, ops)
    assert _chunks(out) == ["IHDR", "IDAT", "IEND"]
    assert Image.open(io.BytesIO(out)).mode == "L"


def test_rotate_expands_and_keeps_ink():
    png = _png()
    out = np.asarray(Image.open(io.BytesIO(apply_ops(png, [{"op": "rotate", "deg": 3.0}]))))
    src = np.asarray(Image.open(io.BytesIO(png)))
    assert out.shape[0] >= src.shape[0] and out.shape[1] >= src.shape[1]
    assert {out[0, 0], out[0, -1], out[-1, 0], out[-1, -1]} == {255}
    assert abs(int((out < 128).sum()) - int((src < 128).sum())) < 0.1 * int((src < 128).sum())


def test_contrast_toward_white():
    out = np.asarray(Image.open(io.BytesIO(apply_ops(_png(), [{"op": "contrast", "c": 0.5}]))))
    assert out.min() == 128 and out.max() == 255


def test_non_gray_rejected():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="PNG")
    with pytest.raises(ValueError):
        apply_ops(buf.getvalue(), [{"op": "blur", "sigma": 0.5}])


def test_opspec_instances_get_the_same_defaults_and_cap_errors_as_dicts():
    from pydantic import ValidationError

    from glyphforge.recipe.schema import OpSpec

    spec = DegradeSpec(blur=OpSpec(p=1.0))
    assert (spec.blur.min, spec.blur.max) == DEGRADE_DEFAULTS["blur"] and spec == DegradeSpec(blur={"p": 1.0})
    with pytest.raises(ValidationError):
        DegradeSpec(blur=OpSpec(p=1, min=0, max=9))
