import importlib

import numpy as np
import pytest

from glyphforge.qc import FLAGS, REASONS, Verdict, pair_integrity, survival, verdict
from glyphforge.render import STATUSES, RenderInfrastructureError, RenderResult
from glyphforge.render.cache import _cache_put

verdict_mod = importlib.import_module("glyphforge.qc.verdict")


def _put(tmp_path, key, arr):
    res = RenderResult(key, "rendered", arr.shape, f"{arr.shape[0]}x{arr.shape[1]}:{arr.tobytes().hex()}")
    _cache_put(tmp_path, res, arr)
    return res


def _crop(extra=0):
    a = np.full((20, 40), 255, dtype=np.uint8)
    a[5:15, 10:30] = 0
    a[2, 2] = 255 - extra
    return a


def _fail(status="compile-failed"):
    return RenderResult("f" * 64, status, None, None)


@pytest.mark.parametrize("status", [s for s in STATUSES if s != "rendered"])
def test_gt_not_rendered_drops_with_status(status):
    v = verdict(RenderResult("a" * 64, status, None, None), [_fail(), _fail()], None, policy="drop")
    assert v == Verdict(False, status, (), 2)


def test_identical_alt_drop_vs_flag(tmp_path):
    gt, alt = _put(tmp_path, "k1", _crop()), _put(tmp_path, "k2", _crop())
    assert verdict(gt, [alt], tmp_path, policy="drop") == Verdict(False, "ambiguous-identical", (), 0)
    v = verdict(gt, [alt], tmp_path, policy="flag")
    assert v.keep and v.reason is None and "ambiguous" in v.flags


def test_near_identical_flag_only(tmp_path):
    gt, alt = _put(tmp_path, "k1", _crop()), _put(tmp_path, "k2", _crop(extra=255))
    v = verdict(gt, [alt], tmp_path, policy="drop")
    assert v.keep and "near-identical" in v.flags and "ambiguous" not in v.flags


def test_identical_after_policy_flag(tmp_path, monkeypatch):
    gt, alt = _put(tmp_path, "k1", _crop()), _put(tmp_path, "k2", _crop(extra=100))
    monkeypatch.setattr(verdict_mod, "apply_policy", lambda img: img.convert("RGB").resize((8, 8)).point(lambda _: 0))
    v = verdict(gt, [alt], tmp_path, policy="drop")
    assert v.keep and "identical-after-policy" in v.flags


def test_unrendered_alt_ignored_and_counted(tmp_path):
    gt = _put(tmp_path, "k1", _crop())
    assert verdict(gt, [_fail()], tmp_path, policy="drop") == Verdict(True, None, (), 1)


def test_policy_and_infra_errors(tmp_path):
    gt = RenderResult("k1", "rendered", (1, 1), "x")
    with pytest.raises(ValueError):
        verdict(gt, [], tmp_path, policy="nope")
    with pytest.raises(RenderInfrastructureError):
        verdict(gt, [RenderResult("k2", "rendered", (1, 1), "y")], tmp_path, policy="drop")


def test_pair_integrity():
    kept, gone = Verdict(True, None), Verdict(False, "ambiguous-identical")
    assert pair_integrity(kept, gone) == (Verdict(False, "pair_partner_dropped"), gone)
    assert pair_integrity(gone, kept) == (gone, Verdict(False, "pair_partner_dropped"))
    assert pair_integrity(kept, kept) == (kept, kept)
    assert pair_integrity(gone, Verdict(False, "overflow")) == (gone, Verdict(False, "overflow"))


def test_survival():
    out = survival(
        [("c@1", "default", None, ()), ("c@1", "default", "compile-failed", ()), ("c@1", "default", None, ("near-identical",))],
        cells=[("c@1", "default"), ("c@1", "libertine")],
    )
    assert out["cells"] == {
        "c@1|default": {"planned": 3, "kept": 2, "dropped": {"compile-failed": 1}, "flags": {"near-identical": 1}},
        "c@1|libertine": {"planned": 0, "kept": 0, "dropped": {}, "flags": {}},
    }
    assert out["zero_yield"] == [["c@1", "libertine"]]
    assert survival([("c", "s", "overflow", ())], [("c", "s")])["zero_yield"] == [["c", "s"]]
    with pytest.raises(ValueError):
        survival([("c", "s", "bogus", ())], [])


def test_vocab():
    assert REASONS[-3:] == ("ambiguous-identical", "pair_partner_dropped", "slot_partner_dropped") and "rendered" not in REASONS
    assert survival([("c", "s", "slot_partner_dropped", ())], [("c", "s")])["cells"]["c|s"]["dropped"] == {"slot_partner_dropped": 1}
    assert FLAGS == ("ambiguous", "identical-after-policy", "near-identical")
