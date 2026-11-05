from __future__ import annotations

import random
from itertools import pairwise

from glyphforge.errors import builtin_registry
from glyphforge.errors.api import Site, Variant
from glyphforge.plan.compose import choose_sites, compose

REG = builtin_registry()


def _desc(cls, latex):
    return tuple(sorted(cls.sites(latex), key=lambda s: s.start, reverse=True))


def test_choose_sites_non_overlapping_sorted_deterministic():
    sites = tuple(Site(s, e, "x") for s, e in ((0, 3), (2, 5), (6, 8), (9, 10)))
    for seed in range(40):
        got = choose_sites(sites, 3, random.Random(seed))
        assert 1 <= len(got) <= 3
        assert all(a.start >= b.end for a, b in pairwise(got))
        assert got == choose_sites(sites, 3, random.Random(seed))
        assert len(choose_sites(sites, 1, random.Random(seed))) == 1


def test_single_site_is_phase2_variant():
    cls, latex = REG.get("greek.upsilon_v"), "v+a_{v}+v^2"
    site = cls.sites(latex)[0]
    assert compose(latex, cls, (site,), random.Random(0)) == cls.apply(latex, site, random.Random(0))


def test_upsilon_three_sites():
    cls, latex = REG.get("greek.upsilon_v"), "v+a_{v}+v^2"
    v = compose(latex, cls, _desc(cls, latex), random.Random(0))
    assert v.target == r"\upsilon+a_{\upsilon}+\upsilon^2" and v.hard_negative == latex
    assert latex in v.target_alternates and len(v.target_alternates) == 4
    assert all(a.count(r"\upsilon") == 2 for a in v.target_alternates if a != latex)
    assert v.target in v.hard_negative_alternates and len(v.hard_negative_alternates) == 4
    assert dict(v.meta)["n_sites"] == "3"


def test_prime_two_sites():
    cls, latex = REG.get("primes.prime_l"), "f'(x)+g'(x)"
    v = compose(latex, cls, _desc(cls, latex), random.Random(0))
    assert (v.target, v.hard_negative) == (latex, "fl(x)+gl(x)")
    assert {"fl(x)+g'(x)", "f'(x)+gl(x)"} <= set(v.hard_negative_alternates) | set(v.target_alternates)


def test_decorations_two_sites_control_glyph_of_leftmost():
    cls, latex = REG.get("decorations.drop_mathbf"), r"\mathbf{x}+\mathbf{y}"
    sites = _desc(cls, latex)
    v = compose(latex, cls, sites, random.Random(0))
    assert v.target == latex and v.hard_negative == "x+y"
    assert v.control_glyph == cls.apply(latex, sites[-1], random.Random(0)).control_glyph


def test_plugin_extras_stay_single_site():
    class Plug:
        name, version, family, packages = "p.q", "1", "p", frozenset()

        def sites(self, latex):
            return (Site(2, 3, "x"), Site(0, 1, "x"))

        def apply(self, latex, site, rng):
            return Variant("T" + str(site.start), "H", "g", ("extra",))

    v = compose("a b", Plug(), Plug().sites(""), random.Random(0))
    assert v == Variant("T0", "H", "g", ("extra",))
