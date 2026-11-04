"""Public error-class API: sites, minimal-pair variants, declarative ConfusionPair / CommandPair."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from glyphforge.canon.tokens import _TOKEN_RE  # same token boundaries as the label path

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")
# Same pattern as recipe.schema.PACKAGE_RE, duplicated as a literal so errors/ never imports pydantic.
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")

_CONTROL_WORD_RE = re.compile(r"\\[A-Za-z]+")
_ENDS_CONTROL_WORD_RE = re.compile(r"\\[A-Za-z]+$")
_DELIMITERS = frozenset(f"\\{b}{s}" for b in ("big", "Big", "bigg", "Bigg") for s in ("", "l", "r", "m")) | {r"\left", r"\right", r"\middle"}

Spans = tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class Site:
    """A candidate location: character offsets into the formula, ``end`` exclusive."""

    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class Variant:
    """The 1:1 minimal pair for one site.

    The hard negative is implicitly the first alternate of the target and vice versa (the pipeline adds it),
    so the ``*_alternates`` fields hold only extra misreads.
    """

    target: str
    hard_negative: str
    control_glyph: str
    target_alternates: tuple[str, ...] = ()
    hard_negative_alternates: tuple[str, ...] = ()
    meta: tuple[tuple[str, str], ...] = ()


@runtime_checkable
class ErrorClass(Protocol):
    """An error class: pure, deterministic, no I/O, no ``\\usepackage`` in its output.

    Ambiguity is measured by QC, never decided by the class.
    """

    name: str
    version: str
    family: str
    packages: frozenset[str]

    def sites(self, latex: str) -> tuple[Site, ...]: ...

    def apply(self, latex: str, site: Site, rng: random.Random) -> Variant: ...


def token_spans(latex: str) -> Spans:
    """(token, start, end) for every non-whitespace token."""
    return tuple((m.group(), m.start(), m.end()) for m in _TOKEN_RE.finditer(latex) if not m.group().isspace())


def splice(latex: str, start: int, end: int, text: str) -> str:
    """Replace ``latex[start:end]`` with ``text``, keeping native spacing; a space is added only where a control word would merge with a letter."""
    prefix, suffix = latex[:start], latex[end:]
    if text[:1].isascii() and text[:1].isalpha() and _ENDS_CONTROL_WORD_RE.search(prefix):
        text = " " + text
    if suffix[:1].isascii() and suffix[:1].isalpha() and _ENDS_CONTROL_WORD_RE.search(text):
        text += " "
    return prefix + text + suffix


def argument_span(spans: Spans, i: int) -> tuple[int, int] | None:
    """Character range of the argument after token ``i``: a balanced brace group or one non-brace token."""
    if i + 1 >= len(spans) or spans[i + 1][0] == "}":
        return None
    if spans[i + 1][0] != "{":
        return spans[i + 1][1], spans[i + 1][2]
    depth = 0
    for tok, _, end in spans[i + 1 :]:
        depth += (tok == "{") - (tok == "}")
        if depth == 0:
            return spans[i + 1][1], end
    return None


def _site_ok(spans: Spans, i: int) -> bool:
    """False inside an environment-name group or right after a delimiter-sizing command."""
    if i and spans[i - 1][0] in _DELIMITERS:
        return False
    j = i - 1
    while j >= 0 and spans[j][0] not in ("{", "}"):
        j -= 1
    return not (j > 0 and spans[j][0] == "{" and spans[j - 1][0] in (r"\begin", r"\end"))


def _check_meta(name: str, version: str, packages: frozenset[str]) -> None:
    if not NAME_RE.match(name):
        raise ValueError(f"bad error-class name {name!r}")
    if not version:
        raise ValueError("version must be non-empty")
    for pkg in packages:
        if not PACKAGE_RE.match(pkg):
            raise ValueError(f"bad package name {pkg!r}")


@dataclass(frozen=True)
class ConfusionPair:
    """Single-token swap: ``truth`` is the label, ``confusable`` is what a model may read instead."""

    name: str
    truth: str
    confusable: str
    family: str
    version: str = "1"
    packages: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _check_meta(self.name, self.version, self.packages)
        if len(token_spans(self.truth)) != 1 or len(token_spans(self.confusable)) != 1 or self.truth == self.confusable:
            raise ValueError(f"{self.name}: truth and confusable must be two different single tokens")

    def sites(self, latex: str) -> tuple[Site, ...]:
        spans = token_spans(latex)
        return tuple(
            Site(s, e, "truth" if tok == self.truth else "confusable")
            for i, (tok, s, e) in enumerate(spans)
            if tok in (self.truth, self.confusable) and _site_ok(spans, i)
        )

    def apply(self, latex: str, site: Site, rng: random.Random) -> Variant:
        return Variant(splice(latex, site.start, site.end, self.truth), splice(latex, site.start, site.end, self.confusable), self.confusable)


@dataclass(frozen=True)
class CommandPair:
    """Command swap (``confusable`` set) or dropped command (``confusable=None``) on a short argument."""

    name: str
    family: str
    truth: str
    confusable: str | None
    version: str = "1"
    packages: frozenset[str] = frozenset()
    arg: str = r"[^{}]{1,8}"
    symmetric: bool = True

    def __post_init__(self) -> None:
        _check_meta(self.name, self.version, self.packages)
        for cmd in (self.truth, self.confusable):
            if cmd is not None and not _CONTROL_WORD_RE.fullmatch(cmd):
                raise ValueError(f"{self.name}: {cmd!r} is not a control word")
        re.compile(self.arg)

    def sites(self, latex: str) -> tuple[Site, ...]:
        kinds = {self.truth: "truth"} | ({self.confusable: "confusable"} if self.symmetric and self.confusable else {})
        spans = token_spans(latex)
        found = []
        for i, (tok, start, _) in enumerate(spans):
            span = argument_span(spans, i) if tok in kinds and _site_ok(spans, i) else None
            if span and re.fullmatch(self.arg, latex[span[0] : span[1]].removeprefix("{").removesuffix("}").strip()):
                found.append(Site(start, span[1], kinds[tok]))
        return tuple(found)

    def apply(self, latex: str, site: Site, rng: random.Random) -> Variant:
        text = latex[site.start : site.end]
        rest = text[len(_CONTROL_WORD_RE.match(text).group()) :]  # type: ignore[union-attr]
        target = splice(latex, site.start, site.end, self.truth + rest)
        if self.confusable is not None:
            return Variant(target, splice(latex, site.start, site.end, self.confusable + rest), self.confusable)
        bare = rest.strip().removeprefix("{").removesuffix("}").strip()
        return Variant(target, splice(latex, site.start, site.end, bare), bare)
