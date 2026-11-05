import importlib.util
from pathlib import Path

import pytest

from glyphforge.render import FONT_BLOCKS, Style, cache_key, docker, render_many

_spec = importlib.util.spec_from_file_location("filter_layer", Path(__file__).parent / "test_filter_layer.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
HOSTILE = _mod.HOSTILE

COLUMN = Style("cm", 10, column_cm=12)


@pytest.mark.parametrize("h", HOSTILE)
def test_hostile_rejected_without_container(h, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("container started for a rejected input")

    monkeypatch.setattr(docker.subprocess, "run", boom)
    results = render_many([f"${h}$", f"{h}\n\\tag{{1}}", f"where ${h}$ ,"], wrapper="line", cache=tmp_path)
    assert [r.status for r in results] == ["rejected"] * 3


def test_cache_key_carries_wrapper():
    assert cache_key("x+1", wrapper="display") != cache_key("x+1", wrapper="line")


def _render(items, tmp_path, style=COLUMN):
    results = render_many(items, wrapper="line", cache=tmp_path, style=style)
    assert [r.status for r in results] == ["rendered"] * len(items)
    return results


@pytest.mark.docker
@pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")
class TestDocker:
    def test_tag_visible(self, tmp_path):
        tagged, bare = _render(["x+1\n\\tag{3}", "x+1"], tmp_path)
        assert tagged.bitmap_sha256 != bare.bitmap_sha256
        assert tagged.shape[1] > bare.shape[1]

    def test_tag_values_differ(self, tmp_path):
        a, b = _render(["x+1\n\\tag{3}", "x+1\n\\tag{4}"], tmp_path)
        assert a.bitmap_sha256 != b.bitmap_sha256

    def test_inline_prime_vs_l(self, tmp_path):
        a, b = _render(["where $x'$ ,", "where $xl$ ,"], tmp_path)
        assert a.bitmap_sha256 != b.bitmap_sha256

    def test_numbered_with_text_math(self, tmp_path):
        """WR-07: a numbered body with \\text{..$i$..} renders (it was rejected as inline text before)."""
        tagged, plain = _render(["x = 0 \\text{ for all $i$}\n\\tag{3}", "x = 0 \\text{ for all }\n\\tag{3}"], tmp_path)
        assert tagged.bitmap_sha256 != plain.bitmap_sha256

    def test_multiline_numbered(self, tmp_path):
        _render(["a&=b\\\\c&=d\n\\tag{2}"], tmp_path)

    def test_fonts_at_8pt(self, tmp_path):
        for font in FONT_BLOCKS:
            _render(["where $\\nu$ ,"], tmp_path, Style(font, 8, column_cm=COLUMN.column_cm))

    def test_column_sets_text_width(self, tmp_path):
        """CR-01: the tag sits at the right edge of the text column, so a wider column gives a wider crop."""
        (narrow,) = _render(["x\n\\tag{1}"], tmp_path, Style("cm", 10, column_cm=8.5))
        (wide,) = _render(["x\n\\tag{1}"], tmp_path, Style("cm", 10, column_cm=15))
        assert wide.shape[1] - narrow.shape[1] > 300  # centred x to right-edge tag spans half the 6.5 cm change: about 384 px at 300 DPI

    def test_no_hyphenation_in_narrow_column(self, tmp_path):
        """WR-02: with hyphenation on, this label wraps to two lines at 5 cm (height 89 px, probed); now it stays one line."""
        label = "where $x$ satisfies the characteristically"
        (narrow,) = _render([label], tmp_path, Style("cm", 10, column_cm=5))
        (wide,) = _render([label], tmp_path, Style("cm", 10, column_cm=30))
        assert narrow.shape[0] == wide.shape[0]

    def test_no_math_break_in_narrow_column(self, tmp_path):
        """Inline math wider than the column must not break after a relation or binary operator (\\relpenalty, \\binoppenalty)."""
        label = "where $a+b+c+d+e+f+g+h=i+j+k+l+m+n+o+p$"
        (narrow,) = _render([label], tmp_path, Style("cm", 10, column_cm=3))
        (wide,) = _render([label], tmp_path, Style("cm", 10, column_cm=30))
        assert narrow.shape[0] == wide.shape[0]
