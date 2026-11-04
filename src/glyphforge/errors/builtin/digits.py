"""Digit/letter look-alikes as declarative ConfusionPairs."""

from __future__ import annotations

from glyphforge.errors.api import ConfusionPair

CLASSES = tuple(
    ConfusionPair(f"digits.{name}", truth, confusable, "digits")
    for name, truth, confusable in (
        ("I_one", "I", "1"),
        ("I_l", "I", "l"),
        ("I_bar", "I", "|"),
        ("l_one", "l", "1"),
        ("l_bar", "l", "|"),
        ("one_bar", "1", "|"),
        ("O_zero", "O", "0"),
        ("ell_l", r"\ell", "l"),
    )
)


def register_classes(registry) -> None:
    for cls in CLASSES:
        registry.register(cls)
