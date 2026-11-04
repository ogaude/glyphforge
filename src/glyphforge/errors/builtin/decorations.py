"""Decorations family: dropped decorations and look-alike swaps as CommandPairs (D-10)."""

from __future__ import annotations

from glyphforge.errors.api import CommandPair

_DROPPED = ("mathbf", "boldsymbol", "bm", "bar", "hat", "tilde", "vec", "dot", "overline", "underline")
_SWAPS = (
    ("bar_overline", "bar", "overline"),
    ("hat_widehat", "hat", "widehat"),
    ("tilde_widetilde", "tilde", "widetilde"),
    ("mathbf_boldsymbol", "mathbf", "boldsymbol"),
    ("mathbf_bm", "mathbf", "bm"),
    ("boldsymbol_bm", "boldsymbol", "bm"),
    ("vec_overrightarrow", "vec", "overrightarrow"),
)
CLASSES = tuple(CommandPair(f"decorations.drop_{c}", "decorations", f"\\{c}", None) for c in _DROPPED) + tuple(
    CommandPair(f"decorations.{n}", "decorations", f"\\{a}", f"\\{b}") for n, a, b in _SWAPS
)


def register_classes(registry) -> None:
    for cls in CLASSES:
        registry.register(cls)
