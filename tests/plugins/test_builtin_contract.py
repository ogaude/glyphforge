"""Every built-in error class passes the public contract helper and registers through the public hook."""

from __future__ import annotations

import random

import pytest

from glyphforge.errors import Registry, check_error_class
from glyphforge.errors.builtin import primes

MODULES = ("primes", "greek", "digits")
EXAMPLES: dict[str, list[str]] = {
    "primes.prime_l": ["f'(x)+g", r"y^{\prime}=x"],
    "primes.dropped": ["f'(x)", "g''+h", r"y^{\prime}"],
    "primes.dquote": ["f''(t)", "a''+b"],
    "greek.upsilon_v": [r"\upsilon_k + a", "v+w"],
    "greek.nu_v": [r"\nu + a", "v+w"],
    "greek.iota_i": [r"\iota + a", "i+j"],
    "greek.kappa_k": [r"\kappa + a", "k+j"],
    "greek.omicron_o": [r"\omicron + a", "o+j"],
    "greek.rho_p": [r"\rho + a", "p+q"],
    "greek.chi_x": [r"\chi + a", "x+y"],
    "digits.I_one": ["I+a", "x_{1}+b"],
    "digits.I_l": ["I+a", "x_{l}+b"],
    "digits.I_bar": ["I+a", "a|b|"],
    "digits.l_one": ["x_{l}+a", "1+b"],
    "digits.l_bar": ["x_{l}+a", "a|b|"],
    "digits.one_bar": ["1+b", "a|b|"],
    "digits.O_zero": ["O(n)+0", "O+a"],
    "digits.ell_l": [r"\ell + a", "l+b"],
}


def _registry(modules=MODULES) -> Registry:
    reg = Registry()
    for m in modules:
        reg.load_module(f"glyphforge.errors.builtin.{m}")
    return reg


def _cases():
    return [(n, e) for n, e in EXAMPLES.items() if n.split(".")[0] in {m for m in MODULES}]


@pytest.mark.parametrize(("name", "formulas"), _cases())
def test_contract(name, formulas):
    assert check_error_class(_registry().get(name), formulas) == []


def test_examples_cover_every_builtin_name():
    assert set(_registry().names()) == {n for n, _ in _cases()}


@pytest.mark.parametrize("module", MODULES)
def test_public_route_only_register(module):
    calls = []

    class Recorder:
        def register(self, obj):
            calls.append(obj.name)

    __import__(f"glyphforge.errors.builtin.{module}", fromlist=["x"]).register_classes(Recorder())
    assert calls and all(c.startswith(module + ".") for c in calls)


def _variant(name, latex, index=0):
    cls = _registry().get(name)
    return cls.apply(latex, cls.sites(latex)[index], random.Random(0))


def test_prime_l():
    v = _variant("primes.prime_l", "f'(x)")
    assert (v.target, v.hard_negative, v.control_glyph) == ("f'(x)", "fl(x)", "l")
    v = _variant("primes.prime_l", r"f^{\prime}(x)")
    assert (v.target, v.hard_negative) == (r"f^{\prime}(x)", "fl(x)")
    assert _registry().get("primes.prime_l").sites("f''") == ()


def test_prime_dropped():
    v = _variant("primes.dropped", "f'(x)")
    assert (v.hard_negative, v.control_glyph) == ("f(x)", "f")
    assert _variant("primes.dropped", "g''").hard_negative == "g"
    assert _variant("primes.dropped", r"y^{\prime}").hard_negative == "y"


def test_prime_dquote():
    v = _variant("primes.dquote", "f''(x)")
    assert (v.target, v.hard_negative, v.control_glyph) == ("f''(x)", 'f"(x)', '"')
    assert primes.CLASSES[2].sites("f'") == () and primes.CLASSES[2].sites("f'''") == ()


def test_omicron_declares_lgrmath():
    reg = _registry()
    assert reg.get("greek.omicron_o").packages == frozenset({"lgrmath"})
    assert all(not reg.get(n).packages for n in reg.names() if n != "greek.omicron_o")
