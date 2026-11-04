"""Walking-skeleton pipeline: recipe -> source -> error classes -> one batched render -> QC -> store -> export."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import PIL

from glyphforge import __version__
from glyphforge.canon import canon_versions
from glyphforge.errors import BUILTIN_MODULES, DEFAULT_REGISTRY, ErrorClass, Registry, Site, Variant, builtin_registry
from glyphforge.export import control_glyphs_used, export_glyphfix
from glyphforge.pixels import PIXEL_POLICY_VERSION
from glyphforge.qc import pair_integrity, survival, verdict
from glyphforge.recipe import SCHEMA_VERSION, Recipe, StyleSpec, frozen_recipe, load_recipe, recipe_sha256, to_style
from glyphforge.render import IMAGE_DIGEST, RenderInfrastructureError, Style, load_bitmap, render_config, render_many
from glyphforge.rng import slot_rng, slot_seed
from glyphforge.sources import load_source
from glyphforge.sources.base import Formula
from glyphforge.store import png_bytes, write_store


def build_registry(recipe: Recipe) -> Registry:
    """Built-ins, library registrations, the recipe's plugin modules and (opt-in) entry points, in a fresh registry."""
    reg = builtin_registry()
    reg.extend(DEFAULT_REGISTRY)
    for module in recipe.plugins:
        reg.load_module(module)
    if recipe.entry_points:
        reg.load_entry_points()
    return reg


def resolve_classes(reg: Registry, names: Sequence[str] | None) -> tuple[ErrorClass, ...]:
    """All classes (sorted by name) for ``None``; otherwise the named classes in recipe order."""
    names = reg.names() if names is None else tuple(names)
    if dupes := sorted({n for n in names if names.count(n) > 1}):
        raise ValueError(f"duplicate error classes in recipe: {dupes}")
    try:
        return tuple(reg.get(n) for n in names)
    except KeyError as exc:
        raise ValueError(exc.args[0]) from exc


@dataclass(frozen=True)
class Candidate:
    slot: int
    pair_id: str
    seed: int
    formula: Formula
    error_class: ErrorClass
    site: Site
    variant: Variant
    style_name: str
    style: Style

    @property
    def class_id(self) -> str:
        return f"{self.error_class.name}@{self.error_class.version}"

    @property
    def target_alternates(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.variant.hard_negative, *self.variant.target_alternates)))

    @property
    def hard_negative_alternates(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.variant.target, *self.variant.hard_negative_alternates)))


def plan_candidates(
    formulas: Sequence[Formula], classes: Sequence[ErrorClass], styles: Sequence[StyleSpec], *, seed: int, recipe_hash: str
) -> list[Candidate]:
    """Expand (formula, class, site, style) in lexicographic order; the slot is the list index."""
    out: list[Candidate] = []
    for f in formulas:
        for cls in classes:
            for site in cls.sites(f.latex):
                variant = cls.apply(f.latex, site, slot_rng(seed, "variant", len(out)))
                for spec in styles:
                    slot = len(out)
                    out.append(
                        Candidate(
                            slot, hashlib.sha256(f"{recipe_hash}:{slot}".encode()).hexdigest()[:16], slot_seed(seed, "variant", slot), f, cls, site,
                            variant, spec.name, to_style(spec, cls.packages),
                        )
                    )
    return out


@dataclass(frozen=True)
class RunResult:
    out_dir: Path
    recipe_sha256: str
    pairs: int
    rows_kept: int
    rows_dropped: int
    survival: dict


def _row(c: Candidate, role: str, label: str, res, v, cache: Path | None, rh: str, images: dict[str, bytes]) -> dict:
    """A store sample row (kept) or ledger row (dropped) for one side of a candidate."""
    sid = f"{c.pair_id}-{'t' if role == 'target' else 'h'}"
    if not v.keep:
        return {"error_class": c.error_class.name, "label": label, "pair_id": c.pair_id, "reason": v.reason, "role": role, "slot": c.slot, "style": c.style_name}
    arr = load_bitmap(res, cache)
    if arr is None:
        raise RenderInfrastructureError("cached bitmap missing or unreadable for a rendered entry; delete the render cache entry and rerun")
    data = png_bytes(arr)
    sha = hashlib.sha256(data).hexdigest()
    images[sha] = data
    f = c.formula
    return {
        "authors": list(f.authors), "bitmap_sha256": res.bitmap_sha256, "class_version": c.error_class.version,
        "control_glyph": c.variant.control_glyph if role == "hard_negative" else None, "env": f.env, "error_class": c.error_class.name,
        "family": c.error_class.family, "flags": sorted(v.flags), "generator_version": __version__, "height": int(arr.shape[0]),
        "image": f"images/{sha[:2]}/{sha}.png", "image_digest": IMAGE_DIGEST, "image_sha256": sha, "label": label, "licence": f.licence,
        "pair_id": c.pair_id, "paper_id": f.paper_id, "paper_version": f.paper_version, "recipe_sha256": rh, "role": role,
        "rules": canon_versions(), "sample_id": sid, "seed": c.seed, "slot": c.slot, "style": c.style_name,
        "style_preamble_sha256": c.style.preamble_sha256, "width": int(arr.shape[1]),
    }


def run(
    recipe: Recipe | Mapping | str | Path,
    out_dir: str | Path,
    *,
    cache: Path | None = None,
    max_parallel: int | None = None,
    batch_size: int = 100,
    base_dir: Path | None = None,
) -> RunResult:
    """Run a recipe end to end into ``out_dir``; the output depends on the recipe only, never on ``max_parallel`` or ``batch_size``."""
    if isinstance(recipe, str | Path):
        base_dir = base_dir or Path(recipe).resolve().parent
        recipe = load_recipe(recipe)
    elif not isinstance(recipe, Recipe):
        recipe = Recipe.model_validate(recipe)
    out_dir = Path(out_dir)
    if (out_dir / "run.json").exists():
        raise FileExistsError(f"{out_dir / 'run.json'} already exists")
    reg = build_registry(recipe)
    classes = resolve_classes(reg, recipe.classes)
    class_ids = [f"{c.name}@{c.version}" for c in classes]
    frozen = frozen_recipe(recipe, class_ids)
    rh = recipe_sha256(frozen)
    formulas = load_source(recipe.source, base_dir or Path.cwd()).formulas()
    cands = plan_candidates(formulas, classes, recipe.styles, seed=recipe.seed, recipe_hash=rh)

    wanted = dict.fromkeys(
        (latex, c.style)
        for c in cands
        for latex in (c.variant.target, c.variant.hard_negative, *c.target_alternates, *c.hard_negative_alternates)
    )
    results = dict(zip(wanted, render_many([k[0] for k in wanted], style=[k[1] for k in wanted], cache=cache, max_parallel=max_parallel, batch_size=batch_size), strict=True))

    samples, ledger, images, entries, not_rendered = [], [], {}, [], 0
    for c in cands:
        v = c.variant
        vt = verdict(results[v.target, c.style], [results[a, c.style] for a in c.target_alternates], cache, policy=recipe.qc.ambiguity)
        vh = verdict(results[v.hard_negative, c.style], [results[a, c.style] for a in c.hard_negative_alternates], cache, policy=recipe.qc.ambiguity)
        vt, vh = pair_integrity(vt, vh)
        not_rendered += vt.alternates_not_rendered + vh.alternates_not_rendered
        for role, label, ver in (("target", v.target, vt), ("hard_negative", v.hard_negative, vh)):
            row = _row(c, role, label, results[label, c.style], ver, cache, rh, images)
            (samples if ver.keep else ledger).append(row)
            entries.append((c.class_id, c.style_name, ver.reason, tuple(sorted(ver.flags))))

    by_reason: dict[str, int] = {}
    for r in ledger:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    run_info = {
        "schema_version": SCHEMA_VERSION, "generator_version": __version__, "seed": recipe.seed, "recipe": frozen, "recipe_sha256": rh,
        "classes": class_ids, "plugins": [m for m in reg.modules if m not in BUILTIN_MODULES], "entry_points": reg.entry_points,
        "styles": {
            s.name: {"font": s.font, "size": s.size, "packages": list(s.packages), "preamble_sha256": to_style(s).preamble_sha256}
            for s in recipe.styles
        },
        "canon_versions": canon_versions(), "render_config": render_config(), "pixel_policy_version": PIXEL_POLICY_VERSION,
        "numpy_version": np.__version__, "pillow_version": PIL.__version__,
        "counts": {
            "pairs": len(cands), "rows_planned": 2 * len(cands), "rows_kept": len(samples), "rows_dropped": len(ledger),
            "by_reason": dict(sorted(by_reason.items())),
        },
        "alternates_not_rendered": not_rendered,
        "survival": (surv := survival(entries, [(cid, s.name) for cid in class_ids for s in recipe.styles])),
        "control_glyphs_used": control_glyphs_used(samples),
    }
    write_store(out_dir, samples, images, ledger, run_info)
    if "glyphfix" in recipe.export.formats:
        export_glyphfix(out_dir, out_dir / "glyphfix")
    return RunResult(out_dir, rh, len(cands), len(samples), len(ledger), surv)
