"""Primes family: ' vs l, dropped primes, '' vs ", with ^{\\prime} as an alternative prime spelling."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from glyphforge.errors.api import Site, Variant, splice, token_spans

_REPLACEMENT = {"l": "l", "dropped": "", "dquote": '"'}


@dataclass(frozen=True)
class Prime:
    name: str
    mode: Literal["l", "dropped", "dquote"]
    family: str = "primes"
    version: str = "1"
    packages: frozenset[str] = frozenset()

    def sites(self, latex: str) -> tuple[Site, ...]:
        spans = token_spans(latex)
        found, i = [], 0
        while i < len(spans):
            tok, start, _ = spans[i]
            j, count = i, 1
            if tok == "'":
                while j + 1 < len(spans) and spans[j + 1][0] == "'" and spans[j + 1][1] == spans[j][2]:
                    j, count = j + 1, count + 1
                kind = "prime"
            elif tok == "^" and i + 3 < len(spans) and spans[i + 1][0] == "{" and spans[i + 2][0] == r"\prime":
                j = i + 2
                while j < len(spans) and spans[j][0] == r"\prime":
                    j += 1
                if j >= len(spans) or spans[j][0] != "}":
                    i += 1
                    continue
                count, kind = j - i - 2, "prime-cmd"
            else:
                i += 1
                continue
            has_base = i > 0 and spans[i - 1][0] != "{"
            ok = {"l": count == 1, "dropped": has_base, "dquote": kind == "prime" and count == 2}[self.mode]
            if ok:
                found.append(Site(start, spans[j][2], kind))
            i = j + 1
        return tuple(found)

    def apply(self, latex: str, site: Site, rng: random.Random) -> Variant:
        glyph = token_spans(latex[: site.start])[-1][0] if self.mode == "dropped" else _REPLACEMENT[self.mode]
        return Variant(latex, splice(latex, site.start, site.end, _REPLACEMENT[self.mode]), glyph)


CLASSES = (Prime("primes.prime_l", "l"), Prime("primes.dropped", "dropped"), Prime("primes.dquote", "dquote"))


def register_classes(registry) -> None:
    for cls in CLASSES:
        registry.register(cls)
