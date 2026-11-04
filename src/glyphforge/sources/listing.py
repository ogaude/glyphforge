"""Phase 2 formula supply: the built-in CC0 seed set, inline recipe lists and JSONL files (D-05)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from glyphforge.sources.base import Formula

if TYPE_CHECKING:  # recipe.schema imports sources.base, so a runtime import here would be circular
    from glyphforge.recipe.schema import SourceSpec

SEED_LICENCE = "CC0-1.0"


@dataclass(frozen=True)
class ListSource:
    """A fixed, ordered list of formulas; each latex string appears once."""

    items: tuple[Formula, ...]

    def __post_init__(self) -> None:
        latex = [f.latex for f in self.items]
        if dupes := sorted({s for s in latex if latex.count(s) > 1}):
            raise ValueError(f"duplicate formulas in source: {dupes}")

    def formulas(self) -> tuple[Formula, ...]:
        return self.items


@cache
def builtin_seed() -> tuple[Formula, ...]:
    """The hand-written CC0 seed set shipped as package data."""
    data = yaml.safe_load(Path(__file__).with_name("seed.yaml").read_text("utf-8"))
    if data["licence"] != SEED_LICENCE:
        raise ValueError(f"seed set licence must be {SEED_LICENCE}")
    return tuple(Formula(**entry, licence=SEED_LICENCE) for entry in data["formulas"])


def load_source(spec: SourceSpec, base_dir: Path) -> ListSource:
    """Build the source a recipe names; file sources must be .jsonl files inside ``base_dir``."""
    if spec.kind == "builtin":
        return ListSource(builtin_seed())
    if spec.kind == "inline":
        return ListSource(spec.formulas)
    root = base_dir.resolve()
    path = (root / spec.path).resolve()
    if Path(spec.path).is_absolute() or not path.is_relative_to(root):
        raise ValueError("source path must stay inside the recipe directory")
    if path.suffix != ".jsonl":
        raise ValueError(f"source file must be .jsonl, got {path.name!r}")
    rows = []
    for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row.setdefault("licence", spec.licence) != spec.licence:
                raise ValueError("row licence differs from the source licence")
            rows.append(Formula.model_validate(row))
        except (ValueError, ValidationError, AttributeError) as exc:
            raise ValueError(f"{spec.path}:{lineno}: {exc}") from exc
    return ListSource(tuple(rows))
