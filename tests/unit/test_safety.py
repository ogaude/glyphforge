import hashlib
import json

import pytest

from glyphforge import canon
from glyphforge.canon import safety as render
from glyphforge.canon.label import CANON_RULES_VERSION
from glyphforge.canon.normalize import NORMALIZE_RULES_VERSION


def test_wrap_equivalent_layouts():
    base = render.wrap("x+1")
    assert render.wrap("$$x+1$$") == base
    assert render.wrap(r"\[x+1\]") == base
    assert render.wrap(r"\begin{equation}x+1\label{a}\end{equation}") == base
    assert render.wrap(r"x+1 \tag{3}") == base
    assert render.wrap(r"x+1 \tag*{3} \nonumber") == base


def test_wrap_aligned():
    w = render.wrap(r"a &= b \\ c &= d")
    assert r"\begin{aligned}" in w and r"\end{aligned}" in w
    assert render.wrap(r"\begin{align}a&=b\\c&=d\end{align}") == render.wrap(r"a&=b\\c&=d")
    assert r"\begin{aligned}" not in render.wrap(r"\begin{pmatrix}a&b\\c&d\end{pmatrix}")


@pytest.mark.parametrize(
    "bad",
    [
        r"\input{/etc/passwd}", r"\include{x}", r"\openin", r"\read", r"\write18{ls}", r"\immediate", r"\catcode",
        r"\def\x{1}", r"\let", r"\gdef", r"\global", r"\newcommand", r"\renewcommand", r"\usepackage{x}", r"\documentclass",
        r"\end{document}", r"\begin{document}", r"\newpage", r"\clearpage", r"\shipout", r"\special", r"\csname",
        r"\makeatletter", r"\jobname", r"\endinput", r"\pagebreak", r"\vspace{100cm}", "a ^^5c b", "a % b", r"a \\% b",
    ],
)
def test_check_safe_rejects(bad):
    assert render.check_safe(bad)


@pytest.mark.parametrize("good", [r"\frac{a}{b}", r"\mathbf{x}", r"\text{if } x", r"a \hspace{1em} b", r"50\%", r"\left( x \right)"])
def test_check_safe_accepts(good):
    assert render.check_safe(good) is None


def test_check_safe_empty():
    assert render.check_safe("") == "empty"
    assert render.check_safe("  \n ") == "empty"


FILTER_DIGEST = "e83853759a64bbb2230cc10d6bcb6fad195fd6edfc54b86ba679bc9c20357f97"


def test_filter_frozen():
    parts = [render._FORBIDDEN_WORDS, render._FORBIDDEN_RE.pattern, render._DOCUMENT_RE.pattern, render._CONTROL_SYMBOL_RE.pattern, render._VERBATIM_ENV_RE.pattern]
    assert hashlib.sha256(json.dumps(parts).encode()).hexdigest() == FILTER_DIGEST


def test_versions_frozen():
    assert (render.WRAP_VERSION, render.FILTER_VERSION, NORMALIZE_RULES_VERSION, CANON_RULES_VERSION) == ("1", "2", "3", "2")
    assert canon.canon_versions() == {"canon_rules_version": "2", "normalize_rules_version": "3", "wrap_version": "1", "filter_version": "2"}
