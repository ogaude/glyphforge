import hashlib
import subprocess
import sys

import pytest

from glyphforge.errors import CommandPair, ConfusionPair, ErrorClass, Site, argument_span, splice, token_spans
from glyphforge.rng import slot_rng, slot_seed

UPS = ConfusionPair("greek.upsilon_v", truth=r"\upsilon", confusable="v", family="greek")


def test_slot_seed_and_rng():
    assert slot_seed(7, "variant", 3, 0) == int.from_bytes(hashlib.sha256(b"7:variant:3:0").digest()[:8], "big")
    assert slot_rng(7, "variant", 3, 0).random() == slot_rng(7, "variant", 3, 0).random()
    assert len({slot_seed(7, "variant", 3, 0), slot_seed(7, "other", 3, 0), slot_seed(7, "variant", 4, 0), slot_seed(7, "variant", 3, 1)}) == 4


def test_token_spans():
    assert token_spans(r"a_{v} + \nu x") == (
        ("a", 0, 1), ("_", 1, 2), ("{", 2, 3), ("v", 3, 4), ("}", 4, 5), ("+", 6, 7), ("\\nu", 8, 11), ("x", 12, 13),
    )


@pytest.mark.parametrize(
    ("latex", "start", "end", "text", "expected"),
    [
        ("a_{v}+b", 3, 4, r"\upsilon", r"a_{\upsilon}+b"),
        (r"\cdot v", 6, 7, r"\upsilon", r"\cdot \upsilon"),
        (r"\cdot\upsilon", 5, 13, "v", r"\cdot v"),
        ("vx", 0, 1, r"\upsilon", r"\upsilon x"),
    ],
)
def test_splice(latex, start, end, text, expected):
    assert splice(latex, start, end, text) == expected


def test_argument_span():
    spans = token_spans(r"\vec{v}_i")
    assert argument_span(spans, 0) == (4, 7)
    assert argument_span(token_spans(r"\bar x"), 0) == (5, 6)
    assert argument_span(token_spans(r"\hat{"), 0) is None
    assert argument_span(token_spans(r"\hat"), 0) is None


def test_confusion_pair_sites_and_apply():
    sites = UPS.sites("a_{v}+v")
    assert [(s.start, s.kind) for s in sites] == [(3, "confusable"), (6, "confusable")]
    v = UPS.apply("a_{v}+v", sites[0], None)
    assert (v.target, v.hard_negative, v.control_glyph) == (r"a_{\upsilon}+v", "a_{v}+v", "v")
    assert isinstance(UPS, ErrorClass)


@pytest.mark.parametrize("latex", [r"\begin{v}x\end{v}", r"\left v", r"\bigl v", r"\Biggr v"])
def test_confusion_pair_excludes_names_and_delimiters(latex):
    assert UPS.sites(latex) == ()


def test_confusion_pair_validation():
    with pytest.raises(ValueError):
        ConfusionPair("greek.x", truth="^{\\prime}", confusable="l", family="g")
    with pytest.raises(ValueError):
        ConfusionPair("Bad Name", truth="a", confusable="b", family="g")
    with pytest.raises(ValueError):
        ConfusionPair("g.x", truth="a", confusable="b", family="g", packages=frozenset({"bad pkg"}))


def test_command_pair_swap():
    c = CommandPair("decorations.bar_overline", family="decorations", truth=r"\bar", confusable=r"\overline")
    x = r"\overline{AB}+c"
    v = c.apply(x, c.sites(x)[0], None)
    assert (v.target, v.hard_negative, v.control_glyph) == (r"\bar{AB}+c", r"\overline{AB}+c", r"\overline")
    assert isinstance(c, ErrorClass)


def test_command_pair_drop():
    c = CommandPair("decorations.drop_mathbf", family="decorations", truth=r"\mathbf", confusable=None)
    x = r"\mathbf{x}+y"
    v = c.apply(x, c.sites(x)[0], None)
    assert (v.target, v.hard_negative, v.control_glyph) == (x, "x+y", "x")
    d = CommandPair("decorations.drop_vec", family="decorations", truth=r"\vec", confusable=None)
    x = r"\vec{v}_i"
    assert d.apply(x, d.sites(x)[0], None).hard_negative == "v_i"


def test_command_pair_arg_and_symmetry():
    assert CommandPair("d.a", family="d", truth=r"\mathcal", confusable=None).sites(r"\mathcal{longargument}") == ()
    assert CommandPair("d.b", family="d", truth=r"\mathcal", confusable=None, arg=r"[A-Z]+").sites(r"\mathcal{x}") == ()
    c = CommandPair("d.c", family="d", truth=r"\bar", confusable=r"\overline", symmetric=False)
    assert c.sites(r"\overline{x}") == () and c.sites(r"\bar{x}") == (Site(0, 7, "truth"),)


def test_errors_import_is_light():
    code = "import sys, glyphforge.errors; assert not {'numpy','pydantic','yaml'} & set(sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
