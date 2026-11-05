import math
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from glyphforge.plan.quota import class_slots, largest_remainder, shortfall, spread, synthetic_paper_ids
from glyphforge.rng import pick


@pytest.mark.parametrize(
    ("total", "shares", "want"),
    [
        (10, {"a": 0.5, "b": 0.5}, {"a": 5, "b": 5}),
        (10, {"a": 0.29, "b": 0.71}, {"a": 3, "b": 7}),
        (100, {"a": 0.29, "b": 0.71}, {"a": 29, "b": 71}),
        (1, {"a": 0.5, "b": 0.5}, {"a": 1, "b": 0}),
        (3, {"a": 1, "b": 2}, {"a": 1, "b": 2}),
        (5, {"a": 0, "b": 1}, {"a": 0, "b": 5}),
    ],
)
def test_largest_remainder(total, shares, want):
    assert largest_remainder(total, shares) == want


@given(st.integers(0, 500), st.lists(st.integers(0, 100), min_size=1, max_size=8).filter(lambda s: sum(s) > 0))
def test_largest_remainder_property(total, weights):
    out = largest_remainder(total, {str(i): w for i, w in enumerate(weights)})
    assert sum(out.values()) == total
    for i, w in enumerate(weights):
        assert abs(out[str(i)] - total * w / sum(weights)) < 1


@given(st.integers(1, 200), st.floats(0, 5, allow_nan=False))
def test_spread_prefix_sums(n, rate):
    q = Fraction(str(rate))
    assert sum(spread(i, rate) for i in range(n)) == math.floor(n * q)


def test_spread_rate():
    assert sum(spread(i, 0.3) for i in range(10)) == 3


def test_class_slots():
    assert class_slots({"a": 3, "b": 1, "c": 2}) == ["a", "b", "c", "a", "c", "a"]


def test_synthetic_paper_ids():
    ids = synthetic_paper_ids([2] * 20, "synth:abcd1234")
    assert ids[:15] == ["synth:abcd1234:0"] * 15
    assert ids[15:] == ["synth:abcd1234:1"] * 5
    assert synthetic_paper_ids([2, 3, 30], "p") == ["p:0", "p:0", "p:1"]


def test_shortfall():
    assert shortfall({"a": 3, "b": 2}, {"a": 3, "b": 1}) == {
        "classes": {"a": {"target": 3, "achieved": 3, "short": 0}, "b": {"target": 2, "achieved": 1, "short": 1}},
        "short_total": 1,
        "short_classes": ["b"],
    }


class _Stub:
    def __init__(self, v):
        self.v, self.calls = v, 0

    def random(self):
        self.calls += 1
        return self.v


def test_pick():
    rng = _Stub(0.5)
    assert pick(rng, ["x", "y"], [0, 1]) == "y"
    assert rng.calls == 1
    assert pick(_Stub(0.999999), ["x", "y", "z"], [1, 1, 1]) == "z"
    for bad in ([0, 0], [-1, 2], [1]):
        with pytest.raises(ValueError):
            pick(_Stub(0.1), ["x", "y"], bad)
