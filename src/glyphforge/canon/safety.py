"""Input safety filter and display wrapper for the render sandbox."""

from __future__ import annotations

import re
from itertools import pairwise

from glyphforge.canon.tokens import DISPLAY_ENVS, tokenize

WRAP_VERSION = "1"
# Bump whenever check_safe, check_render, _FORBIDDEN_WORDS, _FORBIDDEN_PATTERNS, _ALLOWED_ENVS, _ENV_NAME_RE,
# _DOCUMENT_RE or _CONTROL_SYMBOL_RE change, when an existing wrapper's acceptance or body changes, and when the "line" rules
# change after release. It is part of cache_key(), so a bump invalidates every cached render once.
# FILTER_VERSION 3 diverges from glyphfix-math (filter 2) on purpose: CR-01..03 security fix, to be ported upstream.
# 4: the GlyphForge-only "line" wrapper picks the numbered branch by its trailing \tag line before looking for "$" (WR-07).
FILTER_VERSION = "4"


# "display" (default): wrap() re-wraps the body in \[ \]. "env": a starred equation/align/gather environment is typeset verbatim.
# "line": a numbered display ("body\n\tag{n}", decided by that trailing line, so the body may hold \text{..$i$..}) or one text line with
# $..$ inline math, labels in LightOnOCR's native output style.
WRAPPERS = ("display", "env", "line")
_TAG_RE = re.compile(r"^(?P<body>.*\S)\n\\tag\{(?P<n>[1-9][0-9]?)\}$", re.DOTALL)
_TAG_TOKEN_RE = re.compile(r"\\tag(?![A-Za-z])")
_TEXT_RE = re.compile(r"^[A-Za-z0-9 ,.;:()'\-]*$")
_VERBATIM_ENV_RE = re.compile(r"^\\begin\{(equation|align|gather)\*\}.*\\end\{\1\*\}$", re.DOTALL)


_FORBIDDEN_WORDS = ["input", "include", "openin", "openout", "read", "readline", "write", "immediate", "catcode", "lccode", "uccode", "def", "edef", "gdef", "xdef", "let", "futurelet", "global", "outer", "newcommand", "renewcommand", "providecommand", "DeclareMathOperator", "DeclareRobustCommand", "newenvironment", "renewenvironment", "usepackage", "RequirePackage", "documentclass", "newpage", "clearpage", "cleardoublepage", "pagebreak", "shipout", "special", "csname", "endcsname", "makeatletter", "makeatother", "jobname", "endinput", "vspace", "vskip", "pdfprimitive", "directlua", "scantokens", "everymath", "everydisplay", "afterassignment", "expandafter",
    # global-state, file and counter primitives: one prediction must not change how later items in the batch render
    "NewDocumentCommand", "RenewDocumentCommand", "ProvideDocumentCommand", "DeclareDocumentCommand", "NewDocumentEnvironment", "RenewDocumentEnvironment", "NewCommandCopy", "RenewCommandCopy", "DeclareCommandCopy",
    "ExplSyntaxOn", "ExplSyntaxOff", "newcount", "newdimen", "newskip", "newtoks", "newbox", "newif", "newlength", "newcounter", "newtheorem", "newlinechar",
    "setcounter", "addtocounter", "stepcounter", "refstepcounter", "setlength", "addtolength", "setbox", "loop", "repeat",
    "mathchardef", "chardef", "mathcode", "delcode", "sfcode", "DeclareMathSymbol", "DeclareSymbolFont", "DeclareMathAlphabet", "SetMathAlphabet", "DeclareMathAccent", "DeclareMathDelimiter", "DeclareMathRadical", "DeclareFontFamily", "DeclareFontShape",
    "AtEndDocument", "AtBeginDocument", "InputIfFileExists", "IfFileExists", "includegraphics", "includepdf", "pdfximage", "pdfliteral", "pdfobj", "pdfannot", "pdfstartlink", "pdfinfo",
    # always-global and global-mode primitives, deferred-code and insertion primitives
    "fontdimen", "skewchar", "hyphenchar", "globaldefs", "aftergroup", "output", "penalty", "font", "interactionmode", "batchmode", "nonstopmode", "scrollmode", "errorstopmode", "deadcycles", "insertpenalties", "UseName", "ExpandArgs", "primitive",
    "insert", "vadjust", "footnote", "footnotetext", "footnotemark", "marginpar", "mark", "marks", "topinsert", "midinsert", "pageinsert", "enlargethispage"]
# Families rejected by pattern: pdfTeX primitives, \every* token lists, kernel hooks, \At* deferred code, \Before/\After...Environment,
# every global declaration (\Declare*) and capitalised \New*/\Renew*/\Provide*. Lowercase \newline stays accepted. \@namedef needs no
# entry: @ is catcode 12 in the body, so "\@" is a control symbol blanked by _CONTROL_SYMBOL_RE; \makeatletter and \csname are listed above.
_FORBIDDEN_PATTERNS = (r"pdf[A-Za-z]*", r"every[A-Za-z]*", r"[A-Za-z]*Hook[A-Za-z]*", r"At[A-Z][A-Za-z]*", r"[A-Za-z]*Environment", r"Declare[A-Za-z]+", r"(?:New|Renew|Provide)[A-Z][A-Za-z]*")
_FORBIDDEN_RE = re.compile(r"\\(?:" + "|".join([*_FORBIDDEN_WORDS, *_FORBIDDEN_PATTERNS]) + r")(?![A-Za-z])")
# Only these environment names may follow \begin/\end: \begin{<primitive>} would otherwise execute the primitive.
_ALLOWED_ENVS = frozenset(
    {"aligned", "alignedat", "gathered", "lgathered", "rgathered", "split", "multlined", "cases", "dcases", "rcases", "array", "subarray",
     "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "psmallmatrix", "bsmallmatrix", "Bsmallmatrix", "vsmallmatrix", "Vsmallmatrix", *DISPLAY_ENVS}
)
_ENV_NAME_RE = re.compile(r"\\(?:begin|end)(?![A-Za-z])(?:\s*\{([^{}]*)\})?")
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
    for em in _ENV_NAME_RE.finditer(plain):
        if em.group(1) is None:
            return "\\begin/\\end without a literal environment name"
        if _env_name(em) not in _ALLOWED_ENVS:
            return f"environment not allowed: {em.group(1).strip()}"
    m = _FORBIDDEN_RE.search(plain)
    if m:
        return f"forbidden primitive {m.group(0)}"
    return None


def _env_name(m: re.Match[str]) -> str:
    return "".join(m.group(1).split()).removesuffix("*")


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


def render_body(latex: str, wrapper: str = "display") -> str:
    """Exact text compiled for one batch item."""
    if wrapper == "line":
        s = latex.strip()
        if m := _TAG_RE.match(s):
            return wrap(m["body"]).removesuffix("\n\\]") + "\n\\tag{" + m["n"] + "}\n\\]"
        return s if "$" in s else wrap(s)
    return wrap(latex) if wrapper == "display" else latex.strip()


def _check_line(latex: str) -> str | None:
    reason = check_safe(latex)
    if reason:
        return reason
    s = latex.strip()
    m = _TAG_RE.match(s)
    if m is None and "$" in s:
        parts = s.split("$")
        if "$$" in s:
            return "display math escape $$"
        if len(parts) % 2 == 0:
            return "unbalanced $"
        for i, part in enumerate(parts):
            if i % 2 == 0:
                if not _TEXT_RE.match(part):
                    return "text outside the allowed set"
            elif not part.strip():
                return "display math escape $$"
            elif "&" in part or any(t in part for t in ("\\(", "\\)", "\\\\")):
                return "inline math must be one line"
            elif reason := check_render(part, "display"):
                return f"inline math: {reason}"
        return None
    body = m["body"] if m else s
    if _TAG_TOKEN_RE.search(body):
        return "tag must be on its own trailing line"
    return check_render(body, "display")


def check_render(latex: str, wrapper: str = "display") -> str | None:
    """Reason the item must not be rendered, or None. Checks the raw text, the compiled body, and that the item stays in its display group."""
    if wrapper == "line":
        return _check_line(latex)
    reason = check_safe(latex)
    if reason is None and wrapper == "env" and not _VERBATIM_ENV_RE.match(latex.strip()):
        reason = "not a starred display env"
    body = render_body(latex, wrapper)
    reason = reason or check_safe(body)
    if reason:
        return reason
    interior = body[3:-3] if wrapper == "display" else body[body.index("}") + 1 : body.rindex("\\end")]
    toks = tokenize(interior)
    for tok in ("\\[", "\\]"):
        if tok in toks:
            return f"display math escape {tok}"
    if any(a == b == "$" for a, b in pairwise(toks)):
        return "display math escape $$"
    if any(_env_name(m) in DISPLAY_ENVS for m in _ENV_NAME_RE.finditer(interior) if m.group(1) is not None):
        return "nested display environment"
    return None
