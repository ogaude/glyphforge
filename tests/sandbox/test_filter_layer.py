import pytest

from glyphforge.canon.safety import check_render
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
    r"\g\label{}def\x{1}\x",
    r"x \in\label{}put{/etc/hostname}",
    r"\cat\tag{}code",
    r"\end{docu\label{}ment}",
    r"x \begin{openout}3=pwned.txt\end{openout}\begin{write}3{hello}\end{write}\begin{gdef}\Leak{LEAKED}\end{gdef}",
    r"\begin{input}{/etc/passwd}\end{input}",
    r"y \fontdimen22\textfont2=20pt",
    r"\globaldefs=1 \thinmuskip=40mu",
    r"\skewchar\textfont1=0",
    r"\aftergroup\x",
    r"\everypar{x}",
    r"\pdfcatalog{/OpenAction}",
    r"\] \penalty-10000 \[",
    r"x \] \thinmuskip=40mu \[ y",
    r"x $$ \thinmuskip=40mu $$ y",
    r"\UseName{gdef}\Leak{1}",
    r"\AddToHook{env/aligned/begin}{\thinmuskip=40mu}",
    r"\DeclarePairedDelimiter\Leak{(}{)} \Leak{x}",
]


@pytest.mark.parametrize("latex", HOSTILE)
def test_hostile_rejected_without_container(latex, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("container started for a rejected input")

    monkeypatch.setattr(docker.subprocess, "run", boom)
    assert check_render(latex) is not None
    (result,) = render_many([latex], cache=tmp_path)
    assert result.status == "rejected"


def test_env_wrapper_display_escape_rejected_without_container(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("container started for a rejected input")

    monkeypatch.setattr(docker.subprocess, "run", boom)
    latex = r"\begin{equation*}x\end{equation*}\thinmuskip=40mu\begin{equation*}y\end{equation*}"
    (result,) = render_many([latex], cache=tmp_path, wrapper="env")
    assert result.status == "rejected"
