"""Recipe loading (YAML via safe_load, TOML via tomllib), freezing, hashing and Style mapping."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path

import yaml

from glyphforge.recipe.schema import PACKAGE_RE, Recipe, StyleSpec
from glyphforge.render.style import Style


def load_recipe(path: str | Path) -> Recipe:
    """Parse a .yaml/.yml/.toml recipe file into a validated Recipe."""
    path = Path(path)
    match path.suffix.lower():
        case ".yaml" | ".yml":
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        case ".toml":
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        case _:
            raise ValueError(f"unsupported recipe suffix {path.suffix!r}; expected .yaml, .yml or .toml")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("recipe root must be a mapping")  # noqa: TRY004
    return Recipe.model_validate(data)


def frozen_recipe(recipe: Recipe, class_ids: Sequence[str]) -> dict:
    """Expanded recipe with the resolved ``name@version`` class ids in run order."""
    return {**recipe.model_dump(mode="json"), "classes": list(class_ids)}


def recipe_sha256(frozen: dict) -> str:
    """Canonical hash of a frozen recipe (sorted keys, compact separators)."""
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def effective_styles(recipe: Recipe) -> tuple[tuple[StyleSpec, float], ...]:
    """Weighted styles: explicit recipe styles, else fonts x sizes from the typography weights (sorted keys, zero weights omitted)."""
    if recipe.styles is not None:
        return tuple((s, s.weight) for s in recipe.styles)
    t = recipe.typography
    return tuple(
        (StyleSpec(name=f"{f}-{z}pt", font=f, size=z, packages=t.packages, weight=t.fonts[f] * t.sizes[z]), t.fonts[f] * t.sizes[z])
        for f in sorted(t.fonts)
        for z in sorted(t.sizes)
        if t.fonts[f] > 0 and t.sizes[z] > 0
    )


def to_style(spec: StyleSpec, extra_packages: Iterable[str] = (), column_cm: float | None = None) -> Style:
    """Map a StyleSpec (plus class-declared packages) to a Style; preamble lines are built here, never taken from recipe text.

    ``column_cm`` is validated recipe config (a float), appended as a text-width geometry override.
    """
    pkgs = sorted(set(spec.packages) | set(extra_packages))
    if bad := [p for p in pkgs if not re.fullmatch(PACKAGE_RE, p)]:
        raise ValueError(f"invalid package names: {bad}")
    extra = tuple(rf"\usepackage{{{p}}}" for p in pkgs)
    if column_cm is not None:
        extra += (rf"\geometry{{left=1cm,top=1cm,text={{{column_cm:g}cm,17cm}}}}",)
    return Style(spec.font, spec.size, extra)
