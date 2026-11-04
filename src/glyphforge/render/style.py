"""Typography styles: the font package and class size a formula is compiled under."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from glyphforge.render import docker

_DEFAULT_PKGS = r"\usepackage{amsmath,amssymb,amsfonts,mathtools,bm,upgreek,mathrsfs}"
_GEOMETRY = r"\usepackage[paperwidth=40cm,paperheight=20cm,margin=1cm]{geometry}"

# Package load orders verified to compile in the pinned image; never append fonts to the default line outside these recipes.
FONT_BLOCKS: dict[str, tuple[str, ...]] = {
    "cm": (_DEFAULT_PKGS,),
    "lmodern": (_DEFAULT_PKGS, r"\usepackage{lmodern}"),
    "mathpazo": (_DEFAULT_PKGS, r"\usepackage{mathpazo}"),
    "newtx": (r"\usepackage{amsmath,mathtools}", r"\usepackage{newtxtext,newtxmath}", r"\usepackage{bm}", r"\usepackage{upgreek}", r"\usepackage{mathrsfs}"),
    "libertine": (
        r"\usepackage{amsmath,mathtools}", r"\usepackage{libertine}", r"\usepackage[libertine]{newtxmath}",
        r"\usepackage{bm}", r"\usepackage{upgreek}", r"\usepackage{mathrsfs}",
    ),
    "stix2": (r"\usepackage{amsmath,mathtools}", r"\usepackage{stix2}", r"\usepackage{bm}"),
}


@dataclass(frozen=True)
class Style:
    """Font package, class size (8..12 pt) and extra preamble lines.

    ``extra`` is trusted configuration (e.g. a package defining a missing glyph); it must never come from equation text.
    """

    font: str = "cm"
    size: int = 12
    extra: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.font not in FONT_BLOCKS:
            raise ValueError(f"unknown font {self.font!r}; expected one of {tuple(FONT_BLOCKS)}")
        if not 8 <= self.size <= 12:
            raise ValueError(f"size must be in 8..12, got {self.size}")

    @property
    def is_default(self) -> bool:
        return self.font == "cm" and self.size == 12 and not self.extra

    @property
    def preamble(self) -> str:
        if self.is_default:
            return docker.PREAMBLE
        cls = "extarticle" if self.size < 10 else "article"
        lines = [rf"\documentclass[{self.size}pt]{{{cls}}}", _GEOMETRY, *FONT_BLOCKS[self.font], *self.extra, r"\pagestyle{empty}", r"\setlength{\parindent}{0pt}"]
        return "".join(line + "\n" for line in lines)

    @property
    def preamble_sha256(self) -> str:
        """Preamble/grouping key: font package + class size + extras."""
        return docker.PREAMBLE_SHA256 if self.is_default else hashlib.sha256(self.preamble.encode("utf-8")).hexdigest()


DEFAULT_STYLE = Style()
