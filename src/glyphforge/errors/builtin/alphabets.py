"""Alphabets family: dropped math alphabets and cross-swaps as CommandPairs (D-11)."""

from __future__ import annotations

from glyphforge.errors.api import CommandPair

# \mathbb, \mathcal, \mathscr take uppercase arguments only: a lowercase one is undefined or a different glyph in cm,
# so the label would claim a glyph that is not drawn. \mathscr relies on mathrsfs (default preamble and the
# cm/libertine blocks); a font without it yields a reported zero-yield cell, not a backfill.
_UPPER, _ANY = r"[A-Z]{1,8}", r"[^{}]{1,8}"
_UPPER_ONLY = {"mathbb", "mathcal", "mathscr"}
_DROPPED = ("mathbb", "mathrm", "mathcal", "mathscr", "mathfrak", "mathsf")
_SWAPS = (
    ("mathcal_mathscr", "mathcal", "mathscr"),
    ("mathrm_mathsf", "mathrm", "mathsf"),
    ("mathbb_mathbf", "mathbb", "mathbf"),
    ("mathfrak_mathcal", "mathfrak", "mathcal"),
)
CLASSES = tuple(
    CommandPair(f"alphabets.drop_{c}", "alphabets", f"\\{c}", None, arg=_UPPER if c in _UPPER_ONLY else _ANY) for c in _DROPPED
) + tuple(
    CommandPair(f"alphabets.{n}", "alphabets", f"\\{a}", f"\\{b}", arg=_UPPER if _UPPER_ONLY & {a, b} else _ANY) for n, a, b in _SWAPS
)


def register_classes(registry) -> None:
    for cls in CLASSES:
        registry.register(cls)
