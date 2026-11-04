"""Input safety filter and display wrapper for the render sandbox."""

from __future__ import annotations

import re

from glyphforge.canon.tokens import DISPLAY_ENVS

WRAP_VERSION = "1"
# Bump whenever check_safe, _FORBIDDEN_WORDS, _DOCUMENT_RE or _CONTROL_SYMBOL_RE change. It is part of
# cache_key(), so a bump invalidates every cached render once.
FILTER_VERSION = "2"


# "display" (default): wrap() re-wraps the body in \[ \]. "env": a starred equation/align/gather environment is typeset verbatim.
WRAPPERS = ("display", "env")
_VERBATIM_ENV_RE = re.compile(r"^\\begin\{(equation|align|gather)\*\}.*\\end\{\1\*\}$", re.DOTALL)


_FORBIDDEN_WORDS = ["input", "include", "openin", "openout", "read", "readline", "write", "immediate", "catcode", "lccode", "uccode", "def", "edef", "gdef", "xdef", "let", "futurelet", "global", "outer", "newcommand", "renewcommand", "providecommand", "DeclareMathOperator", "DeclareRobustCommand", "newenvironment", "renewenvironment", "usepackage", "RequirePackage", "documentclass", "newpage", "clearpage", "cleardoublepage", "pagebreak", "shipout", "special", "csname", "endcsname", "makeatletter", "makeatother", "jobname", "endinput", "vspace", "vskip", "pdfprimitive", "directlua", "scantokens", "everymath", "everydisplay", "afterassignment", "expandafter",
    # global-state, file and counter primitives: one prediction must not change how later items in the batch render
    "NewDocumentCommand", "RenewDocumentCommand", "ProvideDocumentCommand", "DeclareDocumentCommand", "NewDocumentEnvironment", "RenewDocumentEnvironment", "NewCommandCopy", "RenewCommandCopy", "DeclareCommandCopy",
    "ExplSyntaxOn", "ExplSyntaxOff", "newcount", "newdimen", "newskip", "newtoks", "newbox", "newif", "newlength", "newcounter", "newtheorem", "newlinechar",
    "setcounter", "addtocounter", "stepcounter", "refstepcounter", "setlength", "addtolength", "setbox", "loop", "repeat",
    "mathchardef", "chardef", "mathcode", "delcode", "sfcode", "DeclareMathSymbol", "DeclareSymbolFont", "DeclareMathAlphabet", "SetMathAlphabet", "DeclareMathAccent", "DeclareMathDelimiter", "DeclareMathRadical", "DeclareFontFamily", "DeclareFontShape",
    "AtEndDocument", "AtBeginDocument", "InputIfFileExists", "IfFileExists", "includegraphics", "includepdf", "pdfximage", "pdfliteral", "pdfobj", "pdfannot", "pdfstartlink", "pdfinfo"]
_FORBIDDEN_RE = re.compile(r"\\(?:" + "|".join(_FORBIDDEN_WORDS) + r")(?![A-Za-z])")
_DOCUMENT_RE = re.compile(r"\\(?:begin|end)\s*\{\s*document\s*\}")
_CONTROL_SYMBOL_RE = re.compile(r"\\[^A-Za-z]")


def check_safe(latex: str) -> str | None:
    """Reason the input must not be rendered, or None. Blank input returns "empty"."""
    if not latex or not latex.strip():
        return "empty"
    if "^^" in latex:
        return "TeX character escape ^^"
    if _DOCUMENT_RE.search(latex):
        return "document environment"
    # Control symbols (\\ \% \{ ...) are removed first so "\\%" is seen as a line break plus a comment.
    plain = _CONTROL_SYMBOL_RE.sub(" ", latex)
    if "%" in plain:
        return "unescaped %"
    m = _FORBIDDEN_RE.search(plain)
    if m:
        return f"forbidden primitive {m.group(0)}"
    return None


# --------------------------------------------------------------------------- wrap

_ENV_NAMES = "|".join(re.escape(e) for e in DISPLAY_ENVS)
_ENV_RE = re.compile(r"^\\begin\{(" + _ENV_NAMES + r")(\*?)\}(.*)\\end\{\1\2\}$", re.DOTALL)
_LAYOUT_RES = [
    re.compile(r"\\label\{[^{}]*\}"),
    re.compile(r"\\tag\*?\{[^{}]*\}"),
    re.compile(r"\\(?:nonumber|notag)(?![A-Za-z])"),
]
_INNER_ENV_RE = re.compile(r"\\begin\{([^{}]*)\}(?:(?!\\begin\{).)*?\\end\{\1\}", re.DOTALL)
_BRACE_GROUP_RE = re.compile(r"\{[^{}]*\}")
_ALIGN_RE = re.compile(r"(?<!\\)&|\\\\")


def _strip_outer(s: str) -> str:
    for _ in range(6):
        t = s.strip()
        if t.startswith("$$") and t.endswith("$$") and len(t) >= 4 or t.startswith(r"\[") and t.endswith(r"\]") or t.startswith(r"\(") and t.endswith(r"\)"):
            s = t[2:-2]
        elif t.startswith("$") and t.endswith("$") and len(t) >= 2 and not t.startswith("$$"):
            s = t[1:-1]
        else:
            m = _ENV_RE.match(t)
            if not m:
                return t
            s = m.group(3)
    return s.strip()


def _needs_aligned(body: str) -> bool:
    flat = body
    prev = None
    while prev != flat:
        prev = flat
        flat = _INNER_ENV_RE.sub("", flat)
    prev = None
    while prev != flat:
        prev = flat
        flat = _BRACE_GROUP_RE.sub("", flat)
    return bool(_ALIGN_RE.search(flat))


def wrap(latex: str) -> str:
    """Display body placed in the batch document. Identical for ground truth and prediction."""
    s = latex
    for rx in _LAYOUT_RES:
        s = rx.sub("", s)
    body = _strip_outer(s)
    if _needs_aligned(body):
        body = "\\begin{aligned}\n" + body + "\n\\end{aligned}"
    return "\\[\n" + body + "\n\\]"
