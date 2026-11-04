import pytest

from glyphforge.render import FONT_BLOCKS, Style, docker, render_many

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

BATTERY = (
    r"\upsilon \nu \iota \kappa \rho \chi \ell \mathbf{x} \boldsymbol{x} \bm{x} \mathscr{L} \mathfrak{A} \mathbb{R} \mathcal{L} \mathsf{x} \mathrm{x} "
    r"\bar{x} \hat{x} \tilde{x} \vec{x} \dot{x} \underline{x} \overline{x} f'"
)


def test_font_size_matrix(tmp_path):
    cells = [(f, s) for f in FONT_BLOCKS for s in (8, 10, 12)]
    results = render_many([BATTERY] * len(cells), style=[Style(font=f, size=s) for f, s in cells], cache=tmp_path)
    bad = {c: (r.status, r.note) for c, r in zip(cells, results, strict=True) if r.status != "rendered"}
    assert not bad, bad
    shapes = {c: r.shape for c, r in zip(cells, results, strict=True)}
    assert shapes[("cm", 8)][0] < shapes[("cm", 12)][0], shapes
