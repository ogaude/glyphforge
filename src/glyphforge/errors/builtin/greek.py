"""Greek/Latin look-alikes as declarative ConfusionPairs."""

from __future__ import annotations

from glyphforge.errors.api import ConfusionPair

# \omicron needs lgrmath: it compile-fails in every FONT_BLOCKS font without it. The ambiguity gate decides per font.
CLASSES = (
    ConfusionPair("greek.upsilon_v", r"\upsilon", "v", "greek"),
    ConfusionPair("greek.nu_v", r"\nu", "v", "greek"),
    ConfusionPair("greek.iota_i", r"\iota", "i", "greek"),
    ConfusionPair("greek.kappa_k", r"\kappa", "k", "greek"),
    ConfusionPair("greek.omicron_o", r"\omicron", "o", "greek", packages=frozenset({"lgrmath"})),
    ConfusionPair("greek.rho_p", r"\rho", "p", "greek"),
    ConfusionPair("greek.chi_x", r"\chi", "x", "greek"),
)


def register_classes(registry) -> None:
    for cls in CLASSES:
        registry.register(cls)
