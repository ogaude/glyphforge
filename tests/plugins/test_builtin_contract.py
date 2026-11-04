"""Every built-in error class passes the public contract helper and registers through the public hook."""

from __future__ import annotations

import random

import pytest

from glyphforge.errors import builtin_registry, check_error_class
from glyphforge.errors.builtin import primes

MODULES = ("primes", "greek", "digits", "decorations", "alphabets")
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
    "decorations.drop_mathbf": [r"\mathbf{x}+y"],
    "decorations.drop_boldsymbol": [r"\boldsymbol{x}+y"],
    "decorations.drop_bm": [r"\bm{x}+y"],
    "decorations.drop_bar": [r"\bar{x}+y"],
    "decorations.drop_hat": [r"\hat{p}+y"],
    "decorations.drop_tilde": [r"\tilde{u}+y"],
    "decorations.drop_vec": [r"\vec{v}_i + w"],
    "decorations.drop_dot": [r"\dot{x}+y"],
    "decorations.drop_overline": [r"\overline{AB}"],
    "decorations.drop_underline": [r"\underline{x}+y"],
    "decorations.bar_overline": [r"\bar{x}+\overline{y}"],
    "decorations.hat_widehat": [r"\hat{p}=\widehat{q}"],
    "decorations.tilde_widetilde": [r"\tilde{p}=\widetilde{q}"],
    "decorations.mathbf_boldsymbol": [r"\mathbf{x}+\boldsymbol{y}"],
    "decorations.mathbf_bm": [r"\mathbf{x}+\bm{y}"],
    "decorations.boldsymbol_bm": [r"\boldsymbol{x}+\bm{y}"],
    "decorations.vec_overrightarrow": [r"\vec{v}+\overrightarrow{w}"],
    "alphabets.drop_mathbb": [r"x\in\mathbb{R}"],
    "alphabets.drop_mathrm": [r"\mathrm{d}x"],
    "alphabets.drop_mathcal": [r"\mathcal{L}+a"],
    "alphabets.drop_mathscr": [r"\mathscr{F}+a"],
    "alphabets.drop_mathfrak": [r"\mathfrak{g}"],
    "alphabets.drop_mathsf": [r"\mathsf{T}"],
    "alphabets.mathcal_mathscr": [r"\mathcal{L}+\mathscr{F}"],
    "alphabets.mathrm_mathsf": [r"\mathrm{d}+\mathsf{T}"],
    "alphabets.mathbb_mathbf": [r"\mathbb{R}+\mathbf{N}"],
    "alphabets.mathfrak_mathcal": [r"\mathfrak{G}+\mathcal{L}"],
}


def _registry():
    return builtin_registry()


def _cases():
    return list(EXAMPLES.items())


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


def test_dropped_decorations():
    v = _variant("decorations.drop_vec", r"\vec{v}_i + w")
    assert (v.hard_negative, v.control_glyph) == ("v_i + w", "v")
    v = _variant("decorations.drop_overline", r"\overline{AB}")
    assert (v.hard_negative, v.control_glyph) == ("AB", "AB")


def test_bar_overline_two_sites():
    cls = _registry().get("decorations.bar_overline")
    latex = r"\bar{x}+\overline{y}"
    assert len(cls.sites(latex)) == 2
    v = _variant("decorations.bar_overline", latex, 1)
    assert (v.target, v.hard_negative, v.control_glyph) == (r"\bar{x}+\bar{y}", latex, r"\overline")


def test_alphabets():
    v = _variant("alphabets.drop_mathbb", r"x\in\mathbb{R}")
    assert (v.hard_negative, v.control_glyph) == (r"x\in R", "R")
    assert _variant("alphabets.drop_mathrm", r"\mathrm{d}x").hard_negative == "dx"
    reg = _registry()
    assert reg.get("alphabets.mathbb_mathbf").sites(r"\mathbf{x}") == ()
    assert len(reg.get("alphabets.mathbb_mathbf").sites(r"\mathbf{R}")) == 1
    assert reg.get("alphabets.mathcal_mathscr").sites(r"\mathcal{x}") == ()


def test_registry_shape():
    reg = _registry()
    assert len(reg.names()) == 45
    assert {reg.get(n).family for n in reg.names()} == {"primes", "greek", "digits", "decorations", "alphabets"}
    assert "decorations.boldsymbol_bm" in reg.names()
