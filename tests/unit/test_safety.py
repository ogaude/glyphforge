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


@pytest.mark.parametrize(
    "bad",
    [
        r"\g\label{}def\x{1}\x", r"x \in\label{}put{/etc/hostname}", r"\cat\tag{}code", r"\end{docu\label{}ment}",
        r"x \] \thinmuskip=40mu \[ y", r"x $$ \thinmuskip=40mu $$ y", r"\begin{aligned}x\end{aligned}\end{equation*}",
        r"x \begin{openout}3=pwned.txt\end{openout}", r"\begin{gdef}\Leak{LEAKED}\end{gdef}", r"\begin{input}x\end{input}",
        r"\begin{catcode}x\end{catcode}", r"\begin{ gdef }x", r"\begin{\foo}", r"\begin gdef",
        r"\fontdimen22\textfont2=20pt", r"\skewchar\textfont1=0", r"\hyphenchar\font=0", r"\globaldefs=1", r"\aftergroup\x",
        r"\everypar{x}", r"\everyhbox{x}", r"\everycr{x}", r"\output{x}", r"\penalty-10000", r"\font\x=cmr10", r"\pdfcatalog{}",
        r"\pdfsetmatrix{1 0 0 1}", r"\AddToHook{env/aligned/begin}{x}", r"\AtBeginShipout{x}", r"\BeforeBeginEnvironment{x}",
        r"\UseName{gdef}", r"\ExpandArgs{c}", r"\batchmode", r"\interactionmode=0", r"\deadcycles=0", r"\insert100{x}",
        r"\vadjust{x}", r"\footnote{x}", r"\mark{x}", r"\enlargethispage{1cm}",
        r"\DeclareTextCommand{\x}{OT1}{y}", r"\DeclarePairedDelimiter\Leak{(}{)}", r"\DeclareFixedFont{\x}{OT1}{cmr}{m}{n}{10pt}",
        r"\DeclareTextSymbol{\x}{OT1}{65}", r"\DeclareTextAccent{\x}{OT1}{1}", r"\DeclareOldFontCommand{\x}{y}{z}",
        r"\NewExpandableDocumentCommand{\x}{}{y}", r"\RenewExpandableDocumentCommand{\x}{}{y}",
        r"\ProvideExpandableDocumentCommand{\x}{}{y}", r"\NewCommandCopy\x\y",
    ],
)
def test_check_render_rejects(bad):
    assert render.check_render(bad)


def test_check_render_reasons():
    assert "gdef" in render.check_render(r"\g\label{}def\x{1}\x")
    assert "input" in render.check_render(r"x \in\label{}put{/etc/hostname}")
    assert "catcode" in render.check_render(r"\cat\tag{}code")
    assert render.check_safe(r"\begin{openout}3=x\end{openout}").startswith("environment not allowed")
    assert render.check_safe(r"\begin gdef") == r"\begin/\end without a literal environment name"
    assert render.check_render(r"x \] y").startswith("display math escape")
    assert render.check_render(r"x $$ y").startswith("display math escape")
    assert render.check_render(r"\begin{aligned}x\end{aligned}\end{equation*}") == "nested display environment"
    assert render.check_render(r"\begin{equation*}x\end{align*}", "env") == "not a starred display env"
    assert render.check_render(r"\begin{equation*}x\end{equation*}\thinmuskip=40mu\begin{equation*}y\end{equation*}", "env")


@pytest.mark.parametrize(
    "good",
    [
        r"\frac{a}{b}", r"\mathbf{x}", r"\text{if } x", r"a \hspace{1em} b", r"50\%", r"\left( x \right)", r"a \\[2pt] b",
        r"\text{$x$} + y", r"\allowbreak", r"a \newline b", r"\begin{pmatrix}a&b\\c&d\end{pmatrix}", r"\begin{cases}a\\b\end{cases}",
        r"\begin{array}{cc}a&b\end{array}", r"\begin{split}a&=b\end{split}", r"\begin{smallmatrix}a\end{smallmatrix}",
        r"\begin{gathered}a\end{gathered}", r"\begin{equation}x+1\label{a}\end{equation}", r"\begin{align}a&=b\\c&=d\end{align}",
    ],
)
def test_check_render_accepts(good):
    assert render.check_render(good) is None


def test_check_render_accepts_env():
    assert render.check_render(r"\begin{align*}a&=b\\c&=d\end{align*}", "env") is None


def test_check_safe_empty():
    assert render.check_safe("") == "empty"
    assert render.check_safe("  \n ") == "empty"


FILTER_DIGEST = "572fc41ba94bb899a5bea5e0b2be19cd36544a3ec56c8e2c7c5147a1398b4397"


def test_filter_frozen():
    parts = [render._FORBIDDEN_WORDS, list(render._FORBIDDEN_PATTERNS), sorted(render._ALLOWED_ENVS), render._FORBIDDEN_RE.pattern, render._ENV_NAME_RE.pattern, render._DOCUMENT_RE.pattern, render._CONTROL_SYMBOL_RE.pattern, render._VERBATIM_ENV_RE.pattern]
    assert hashlib.sha256(json.dumps(parts).encode()).hexdigest() == FILTER_DIGEST


def test_versions_frozen():
    assert (render.WRAP_VERSION, render.FILTER_VERSION, NORMALIZE_RULES_VERSION, CANON_RULES_VERSION) == ("1", "4", "3", "2")
    assert canon.canon_versions() == {"canon_rules_version": "2", "normalize_rules_version": "3", "wrap_version": "1", "filter_version": "4"}
