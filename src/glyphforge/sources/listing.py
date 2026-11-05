"""Phase 2 formula supply: the built-in CC0 seed set, inline recipe lists and JSONL files (D-05)."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from glyphforge.sources.base import Formula

if TYPE_CHECKING:  # recipe.schema imports sources.base, so a runtime import here would be circular
    from glyphforge.errors.api import ErrorClass
    from glyphforge.recipe.schema import SourceSpec
    from glyphforge.sources.grammar import GrammarSource
    from glyphforge.sources.mutation import MutationSource

SEED_LICENCE = "CC0-1.0"


@dataclass(frozen=True)
class ListSource:
    """A fixed, ordered list of formulas; each latex string appears once. ``sha256`` pins a file source's content."""

    items: tuple[Formula, ...]
    sha256: str | None = None
    _index: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        if dupes := sorted(s for s, n in Counter(f.latex for f in self.items).items() if n > 1):
            raise ValueError(f"duplicate formulas in source: {dupes}")

    def formulas(self) -> tuple[Formula, ...]:
        return self.items

    def draw(self, cls: ErrorClass, rng: random.Random, *, level: str | None = None, multiline: bool = False) -> Formula | None:
        """A formula with at least one site of ``cls``, or None; ``level`` and ``multiline`` are unused here."""
        i = _draw_index([f.latex for f in self.items], cls, rng, self._index)
        return None if i is None else self.items[i]


def _draw_index(latexes: Sequence[str], cls: ErrorClass, rng: random.Random, cache: dict) -> int | None:
    """Pick a row index uniformly among rows where ``cls`` has a site; the site index is built once per class version."""
    key = (cls.name, cls.version)
    if key not in cache:
        cache[key] = tuple(i for i, s in enumerate(latexes) if cls.sites(s))
    idx = cache[key]
    return idx[int(rng.random() * len(idx))] if idx else None


def _resolve_inside(base_dir: Path, rel: str, suffix: str) -> Path:
    """Resolve ``rel`` under ``base_dir``; reject absolute paths, escapes and the wrong suffix."""
    root = base_dir.resolve()
    path = (root / rel).resolve()
    if Path(rel).is_absolute() or not path.is_relative_to(root):
        raise ValueError("source path must stay inside the recipe directory")
    if path.suffix != suffix:
        raise ValueError(f"source file must be {suffix}, got {path.name!r}")
    return path


@cache
def builtin_seed() -> tuple[Formula, ...]:
    """The hand-written CC0 seed set shipped as package data."""
    data = yaml.safe_load(Path(__file__).with_name("seed.yaml").read_text("utf-8"))
    if data["licence"] != SEED_LICENCE:
        raise ValueError(f"seed set licence must be {SEED_LICENCE}")
    return tuple(Formula(**entry, licence=SEED_LICENCE) for entry in data["formulas"])


def load_source(spec: SourceSpec, base_dir: Path) -> ListSource | MutationSource | GrammarSource:
    """Build the source a recipe names; file sources must be .jsonl files inside ``base_dir``."""
    if spec.kind == "builtin":
        return ListSource(builtin_seed())
    if spec.kind == "inline":
        return ListSource(spec.formulas)
    if spec.kind == "grammar":
        from glyphforge.sources.grammar import GrammarSource  # grammar imports plan.bounds

        return GrammarSource(spec.domains)
    if spec.kind == "mutation":
        from glyphforge.sources.mutation import load_snapshot  # mutation imports this module's helpers

        return load_snapshot(spec, base_dir)
    data = _resolve_inside(base_dir, spec.path, ".jsonl").read_bytes()
    rows = []
    for lineno, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row.setdefault("licence", spec.licence) != spec.licence:
                raise ValueError("row licence differs from the source licence")
            rows.append(Formula.model_validate(row))
        except (ValueError, ValidationError, AttributeError) as exc:
            raise ValueError(f"{spec.path}:{lineno}: {exc}") from exc
    return ListSource(tuple(rows), hashlib.sha256(data).hexdigest())
