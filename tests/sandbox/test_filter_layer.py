import pytest

from glyphforge.canon.safety import check_safe
from glyphforge.render import docker, render_many

HOSTILE = [
    r"\input{/etc/passwd}",
    r"\include{x}",
    r"\write18{touch pwned}",
    r"\immediate\write18{touch pwned}",
    r"\openin1=/etc/passwd",
    r"\read1to\x",
    r"\def\a{\a}\a",
    r"\csname input\endcsname{/etc/passwd}",
    r"^^5cinput{/etc/passwd}",
    r"x % comment",
    r"\begin{document}",
    r"\usepackage{shellesc}",
]


@pytest.mark.parametrize("latex", HOSTILE)
def test_hostile_rejected_without_container(latex, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("container started for a rejected input")

    monkeypatch.setattr(docker.subprocess, "run", boom)
    assert check_safe(latex) is not None
    (result,) = render_many([latex], cache=tmp_path)
    assert result.status == "rejected"
