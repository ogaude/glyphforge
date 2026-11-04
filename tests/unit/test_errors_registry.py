import importlib.metadata
import sys
import types
from dataclasses import dataclass

import pytest

from glyphforge.errors import ConfusionPair, Registry, Site, Variant, check_error_class, pairs_from_alignment, register
from glyphforge.errors import registry as registry_mod

UPS = ConfusionPair("greek.upsilon_v", truth=r"\upsilon", confusable="v", family="greek")


def test_register_get_names():
    reg = Registry()
    assert reg.register(UPS) is UPS
    with pytest.raises(ValueError):
        reg.register(UPS)
    with pytest.raises(TypeError):
        reg.register(object())
    with pytest.raises(KeyError, match=r"did you mean.*greek\.upsilon_v"):
        reg.get("greek.upsilon_vv")
    reg.register(ConfusionPair("a.b", truth="a", confusable="b", family="a"))
    assert reg.names() == ("a.b", "greek.upsilon_v")
    assert reg.ids() == ("a.b@1", "greek.upsilon_v@1")


def test_default_registry_library_route():
    from glyphforge.errors import DEFAULT_REGISTRY

    obj = register(ConfusionPair("lib.route_test", truth="a", confusable="b", family="lib"))
    assert DEFAULT_REGISTRY.get("lib.route_test") is obj


def test_load_module(monkeypatch):
    mod = types.ModuleType("tests_plugin_mod")
    mod.register_classes = lambda r: r.register(ConfusionPair("plug.a_b", truth="a", confusable="b", family="plug"))
    monkeypatch.setitem(sys.modules, "tests_plugin_mod", mod)
    monkeypatch.setitem(sys.modules, "tests_plugin_bare", types.ModuleType("tests_plugin_bare"))
    reg = Registry()
    reg.load_module("tests_plugin_mod")
    assert reg.names() == ("plug.a_b",) and reg.modules == ["tests_plugin_mod"]
    with pytest.raises(ValueError):
        reg.load_module("tests_plugin_bare")
    for bad in ("os; rm", "../x"):
        with pytest.raises(ValueError):
            reg.load_module(bad)


class _EP:
    def __init__(self, name, obj, dist=None):
        self.name, self._obj, self.dist = name, obj, dist

    def load(self):
        return self._obj


def test_load_entry_points(monkeypatch):
    dist = types.SimpleNamespace(name="pkg", version="1.2")
    eps = [
        _EP("b_call", lambda r: r.register(ConfusionPair("ep.call", truth="a", confusable="b", family="ep"))),
        _EP("a_obj", ConfusionPair("ep.obj", truth="c", confusable="d", family="ep"), dist),
    ]
    seen = {}
    monkeypatch.setattr(registry_mod.importlib.metadata, "entry_points", lambda group: seen.update(group=group) or eps)
    reg = Registry()
    reg.load_entry_points()
    assert seen["group"] == "glyphforge.error_classes"
    assert reg.names() == ("ep.call", "ep.obj") and reg.entry_points == ["a_obj=pkg@1.2", "b_call"]
    assert importlib.metadata.entry_points is not None


@dataclass(frozen=True)
class _Fake:
    out: tuple[str, str] = ("a+b", "a+c")
    name: str = "fake.cls"
    version: str = "1"
    family: str = "fake"
    packages: frozenset[str] = frozenset()

    def sites(self, latex):
        return (Site(0, 1, "x"),)

    def apply(self, latex, site, rng):
        return Variant(self.out[0], self.out[1], "c")


def test_check_valid_and_failures():
    assert check_error_class(UPS, ["a_{v}+b"]) == []
    for out, needle in [
        (("a+b", "a+b"), "normalize-equal"),
        (("a+{b", "a+b"), "unbalanced"),
        ((r"\usepackage{x}", "a"), "usepackage"),
        ((r"\label{a}x", "a"), "rewritten by canon"),
    ]:
        assert any(needle in p for p in check_error_class(_Fake(out), ["ab"])), (out, needle)
    assert any("no sites" in p for p in check_error_class(UPS, ["abc"]))


def test_check_nondeterministic():
    class Flip(_Fake):
        calls = 0

        def sites(self, latex):
            Flip.calls += 1
            return (Site(0, 1, "x"),) * (Flip.calls % 2 + 1)

    assert any("non-deterministic" in p for p in check_error_class(Flip(), ["ab"]))

    class Order(_Fake):
        n = 0

        def apply(self, latex, site, rng):
            Order.n += 1
            return Variant(f"a{Order.n}", "b", "c")

    assert any("non-deterministic" in p for p in check_error_class(Order(), ["ab"]))


def test_pairs_from_alignment():
    rows = [("\\upsilon", "v", 5), ("\\nu", "v", 9), ("'", "\\prime", 3), ("\\upsilon", "v", 2), ("ab", "x", 1)]
    assert [p.name for p in pairs_from_alignment(rows)] == ["mined.nu_v", "mined.upsilon_v"]
    assert [p.name for p in pairs_from_alignment(rows, min_count=8)] == ["mined.nu_v"]
    assert pairs_from_alignment([("'", "l", 1)])[0].name == "mined.u27_l"
