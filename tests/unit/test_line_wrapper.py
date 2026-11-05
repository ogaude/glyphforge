import importlib.util
from pathlib import Path

import pytest

from glyphforge.canon.safety import FILTER_VERSION, WRAP_VERSION, WRAPPERS, check_render, render_body, wrap

_spec = importlib.util.spec_from_file_location("filter_layer", Path(__file__).parents[1] / "sandbox" / "test_filter_layer.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HOSTILE = _mod.HOSTILE

ACCEPTED = ["x+1\n\\tag{3}", "where $x'$ ,", "$a_{v}$ and $b$ .", "x'", "for all $n$", "a&=b\\\\c&=d\n\\tag{12}"]
REJECTED = [
    "x\n\\tag{3}\n\\tag{4}", "x\n\\tag{abc}", "x\n\\tag{3a}", "x\n\\tag{l}", "x\n\\tag{0}", "x\n\\tag{07}", "x\n\\tag{100}", "x\\tag{3}",
    "$x$ \\input{y}", "$x", "where $$x$$", "$x \\[ y$", "text \\textbf{a} $x$", "$a \\\\ b$", "$a & b$", "$\\(x\\)$", "$$", "",
    "x % c\n\\tag{1}", "a\n\\tag{1} $b$",
]


def test_versions_and_wrappers():
    assert WRAPPERS == ("display", "env", "line")
    assert (WRAP_VERSION, FILTER_VERSION) == ("1", "3")


def test_numbered_body():
    assert render_body("x+1\n\\tag{3}", "line") == wrap("x+1").removesuffix("\n\\]") + "\n\\tag{3}\n\\]"
    aligned = render_body("a&=b\\\\c&=d\n\\tag{12}", "line")
    assert aligned.index("\\end{aligned}") < aligned.index("\\tag{12}")


def test_text_and_bare_bodies():
    assert render_body("  where $x'$ , ", "line") == "where $x'$ ,"
    assert render_body("x'", "line") == wrap("x'")


@pytest.mark.parametrize("latex", ACCEPTED)
def test_accepted(latex):
    assert check_render(latex, "line") is None


@pytest.mark.parametrize("latex", REJECTED)
def test_rejected(latex):
    assert check_render(latex, "line") is not None


@pytest.mark.parametrize("h", HOSTILE)
def test_hostile_rejected(h):
    assert check_render(f"${h}$", "line") is not None
    assert check_render(f"{h}\n\\tag{{1}}", "line") is not None
