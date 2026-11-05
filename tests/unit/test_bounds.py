import pytest

from glyphforge.errors.api import Site
from glyphforge.plan.bounds import TOKEN_FIT, bounds_problem, est_tokens, nesting_depth, script_count, site_level


def test_est_tokens():
    assert TOKEN_FIT == (0.92, 6.5)
    assert est_tokens("x") == 7
    assert est_tokens(r"\frac{a}{b}") == 13


def test_depth_and_scripts():
    assert nesting_depth("a_{b_{c}}") == 2
    assert nesting_depth("x") == 0
    assert script_count("a_{b}^{c}+d_e") == 3


@pytest.mark.parametrize(
    ("latex", "needle", "want"),
    [
        ("x'", "'", "base"),
        ("a_{x'}", "x", "script"),
        ("a_{x'}", "'", "script"),
        ("a_{b_{x'}}", "x", "scriptscript"),
        ("a^x", "x", "script"),
        (r"\frac{v}{2}", "v", "base"),
    ],
)
def test_site_level(latex, needle, want):
    i = latex.index(needle)
    assert site_level(latex, Site(i, i + len(needle), "k")) == want


def test_bounds_problem():
    kw = {"max_tokens": 100, "max_depth": 2, "max_scripts": 3}
    assert bounds_problem("x", **kw) is None
    assert bounds_problem("x " * 200, **kw) == "over-token-cap"
    assert bounds_problem("a_{b_{c_{d}}}", **kw) == "too-deep"
    assert bounds_problem("a_b+c_d+e_f+g_h", **kw) == "too-many-scripts"
    assert bounds_problem("x", counter=lambda s: 999, **kw) == "over-token-cap"
