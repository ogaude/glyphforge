"""Docker-free checks behind ``glyphforge validate``: recipe schema, class resolution, pinned-file hashes and store integrity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from glyphforge.export.leak import load_blocklist
from glyphforge.fileio import file_sha256
from glyphforge.pipeline import build_registry, resolve_classes
from glyphforge.recipe import SCHEMA_VERSION, Recipe, frozen_recipe, load_recipe, recipe_sha256
from glyphforge.sources.listing import resolve_inside


def field_errors(exc: ValidationError) -> list[str]:
    """One ``dotted.path: message`` string per schema error."""
    return [".".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in exc.errors()]


def schema_text() -> str:
    """The published recipe JSON Schema text (what ``schema.json`` holds)."""
    return json.dumps(Recipe.model_json_schema(), indent=2, sort_keys=True) + "\n"


def validate_recipe(path: Path) -> dict:
    """Schema, class resolution and pin checks for a recipe file; schema and class errors propagate as ValidationError / ValueError."""
    path = Path(path)
    recipe = load_recipe(path)
    base_dir = path.resolve().parent
    class_ids = [f"{c.name}@{c.version}" for c in resolve_classes(build_registry(recipe), recipe.classes)]
    spec = recipe.source
    pins = [("mutation", p.path, p.sha256) for p in (spec.parts if spec.kind == "mix" else (spec,)) if p.kind == "mutation"]
    if recipe.export.blocklist:
        pins.append(("blocklist", recipe.export.blocklist.path, recipe.export.blocklist.sha256))
    results, problems = [], []
    for kind, rel, pinned in pins:
        file = resolve_inside(base_dir, rel, ".jsonl")
        actual = file_sha256(file) if file.is_file() else None
        if actual is None:
            problems.append(f"{rel}: file not found")
        elif actual != pinned:
            problems.append(f"{kind} sha256 mismatch: recipe pins {pinned}, file is {actual}")
        elif kind == "blocklist":
            load_blocklist(recipe.export.blocklist, base_dir)  # malformed lines raise ValueError
        results.append({"kind": kind, "path": rel, "sha256": pinned, "ok": actual == pinned})
    return {
        "ok": not problems, "recipe_sha256": recipe_sha256(frozen_recipe(recipe, class_ids)), "schema_version": recipe.schema_version,
        "classes": class_ids, "pins": results, "problems": problems,
    }  # fmt: skip


def check_store(store_dir: Path) -> list[str]:
    """Problem strings for a store directory (empty when intact); unreadable JSON is reported, not raised."""
    root, problems = Path(store_dir), []

    def rows(name: str) -> list[dict]:
        try:
            return [json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError) as exc:
            problems.append(f"{name} unreadable: {exc}")
            return []

    if not (root / "run.json").is_file():
        problems.append("run.json missing")
    else:
        try:
            if json.loads((root / "run.json").read_text(encoding="utf-8")).get("schema_version", 0) < SCHEMA_VERSION:
                problems.append(f"store predates schema {SCHEMA_VERSION}")
        except (OSError, ValueError) as exc:
            problems.append(f"run.json unreadable: {exc}")
    samples = rows("samples.jsonl")
    for sha in sorted({s["image_sha256"] for s in samples}):
        png = root / "images" / sha[:2] / f"{sha}.png"
        if not png.is_file() or hashlib.sha256(png.read_bytes()).hexdigest() != sha:
            problems.append(f"image {sha} missing or corrupt")
    by_pair: dict[str, list[str]] = {}
    for s in samples:
        if s["pair_id"] is not None:
            by_pair.setdefault(s["pair_id"], []).append(s["role"] if s["control_kind"] == "pair" else s["control_kind"])
    problems += [f"pair {pid} incomplete" for pid, roles in sorted(by_pair.items()) if sorted(roles) != ["hard_negative", "target"]]
    return problems
