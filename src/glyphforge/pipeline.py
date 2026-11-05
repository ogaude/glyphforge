"""Pipeline: recipe -> quota planner -> rendering in refill rounds -> QC -> store -> export."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import PIL

from glyphforge import __version__
from glyphforge.canon import canon_versions
from glyphforge.errors import BUILTIN_MODULES, DEFAULT_REGISTRY, ErrorClass, Registry, builtin_registry
from glyphforge.export import control_glyphs_used, export_glyphfix
from glyphforge.pixels import PIXEL_POLICY_VERSION
from glyphforge.plan import TOKEN_FIT, build_context, draw_slot, shortfall
from glyphforge.plan.draw import Control, Draft, DrawContext
from glyphforge.qc import pair_integrity, survival, verdict
from glyphforge.recipe import SCHEMA_VERSION, Recipe, frozen_recipe, load_recipe, recipe_sha256, to_style
from glyphforge.render import IMAGE_DIGEST, RenderInfrastructureError, load_bitmap, render_config, render_many
from glyphforge.report import balance_report, scale_report
from glyphforge.sources.grammar import TABLE_VERSION
from glyphforge.store import JOURNAL, png_bytes, read_journal, write_round, write_store


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
class RunResult:
    out_dir: Path
    recipe_sha256: str
    slots_planned: int
    rows_kept: int
    rows_dropped: int
    survival: dict
    shortfall: dict
    warnings: list[str]


def _row(d: Draft, c: Control | None, role: str, label: str, res, v, cache: Path | None, rh: str, pad_px: int, images: dict[str, bytes]) -> dict:
    """A store sample row (kept) or ledger row (dropped) for one label of a draft; ``c`` is set for an extra control."""
    f = c.formula if c else d.formula
    look = d.look
    row = {
        "attempt": d.attempt, "control_kind": "extra" if c else "pair", "error_class": d.slot.error_class.name, "font": look.style.font,
        "label": label, "pair_id": None if c else d.slot.pair_id, "reason": v.reason, "role": role,
        "sample_id": f"{d.slot.pair_id}-" + (f"c{c.index}" if c else role[0]), "slot": d.slot.index, "source": d.source_kind,
        "structure": look.structure, "style": look.style.name,
    }  # fmt: skip
    if not v.keep:
        return row
    arr = load_bitmap(res, cache)
    if arr is None:
        raise RenderInfrastructureError("cached bitmap missing or unreadable for a rendered entry; delete the render cache entry and rerun")
    padded = np.pad(arr, pad_px, constant_values=255) if pad_px else arr
    data = png_bytes(padded)
    sha = hashlib.sha256(data).hexdigest()
    images[sha] = data
    del row["reason"]
    return row | {
        "authors": list(f.authors), "bitmap_sha256": res.bitmap_sha256, "class_version": d.slot.error_class.version,
        "column_cm": look.column_cm, "control_glyph": (c.control_glyph if c else d.variant.control_glyph) if role == "hard_negative" else None,
        "env": f.env, "family": d.slot.error_class.family, "flags": sorted(v.flags), "generator_version": __version__,
        "height": int(padded.shape[0]), "image": f"images/{sha[:2]}/{sha}.png", "image_digest": IMAGE_DIGEST, "image_sha256": sha,
        "licence": f.licence, "n_sites": 1 if c else d.n_sites, "n_tokens": c.n_tokens if c else d.n_tokens, "pad_px": pad_px,
        "paper_id": f.paper_id, "paper_version": f.paper_version, "recipe_sha256": rh, "rules": canon_versions(), "seed": d.seed,
        "site_level": c.site_level if c else d.site_level, "size_pt": look.style.size, "style_preamble_sha256": d.style.preamble_sha256,
        "width": int(padded.shape[1]), "wrapper": d.wrapper,
    }  # fmt: skip


def _round(
    open_slots: Sequence, attempt: int, ctx: DrawContext, recipe: Recipe, rh: str, cache: Path | None, max_parallel: int | None, batch_size: int
) -> tuple[dict[int, list[dict]], list[dict], dict[str, bytes], list[tuple], int, int]:
    """Draw and render every open slot once (one render_many per wrapper); a slot is kept only when all its rows pass QC.

    Returns (kept rows by slot, ledger rows, images, survival entries, slots without a drawable formula, alternates not rendered).
    """
    drafts = [d for s in open_slots if (d := draw_slot(s, attempt, ctx)) is not None]
    wanted = {
        w: dict.fromkeys(
            (x, d.style)
            for d in drafts
            if d.wrapper == w
            for x in (d.target, d.hard_negative, *d.target_alternates, *d.hard_negative_alternates, *(y for c in d.controls for y in (c.label, *c.alternates)))
        )
        for w in ("display", "line")
    }  # fmt: skip
    results: dict[tuple, dict] = {}
    for w, keys in wanted.items():
        if keys:
            rendered = render_many([k[0] for k in keys], wrapper=w, style=[k[1] for k in keys], cache=cache, max_parallel=max_parallel, batch_size=batch_size)
            for (latex, style), r in zip(keys, rendered, strict=True):
                results.setdefault((w, style), {})[latex] = r
    kept, ledger, images, entries, not_rendered = {}, [], {}, [], 0
    pol, pad = recipe.qc.ambiguity, recipe.render.pad_px
    for d in drafts:
        res = results[d.wrapper, d.style]
        vt, vh = pair_integrity(
            verdict(res[d.target], [res[a] for a in d.target_alternates], cache, policy=pol),
            verdict(res[d.hard_negative], [res[a] for a in d.hard_negative_alternates], cache, policy=pol),
        )
        parts = [(None, "target", d.target, vt), (None, "hard_negative", d.hard_negative, vh)] + [
            (c, "hard_negative", c.label, verdict(res[c.label], [res[a] for a in c.alternates], cache, policy=pol)) for c in d.controls
        ]
        not_rendered += sum(p[3].alternates_not_rendered for p in parts)
        ok, rows = all(p[3].keep for p in parts), []
        for c, role, label, v in parts:
            v = v if ok or not v.keep else replace(v, keep=False, reason="slot_partner_dropped")
            row = _row(d, c, role, label, res[label], v, cache, rh, pad, images)
            (rows if v.keep else ledger).append(row)
            entries.append((f"{d.slot.error_class.name}@{d.slot.error_class.version}", d.look.style.font, v.reason, tuple(sorted(v.flags))))
        if ok:
            kept[d.slot.index] = rows
    return kept, ledger, images, entries, len(open_slots) - len(drafts), not_rendered


def run(
    recipe: Recipe | Mapping | str | Path,
    out_dir: str | Path,
    *,
    cache: Path | None = None,
    max_parallel: int | None = None,
    batch_size: int = 100,
    base_dir: Path | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> RunResult:
    """Run a recipe end to end into ``out_dir``; the output depends on the recipe only, never on ``max_parallel`` or ``batch_size``."""
    if isinstance(recipe, str | Path):
        base_dir = base_dir or Path(recipe).resolve().parent
        recipe = load_recipe(recipe)
    elif not isinstance(recipe, Recipe):
        recipe = Recipe.model_validate(recipe)
    out_dir, base_dir = Path(out_dir), base_dir or Path.cwd()
    if (out_dir / "run.json").exists():
        raise FileExistsError(f"{out_dir / 'run.json'} already exists")
    reg = build_registry(recipe)
    classes = resolve_classes(reg, recipe.classes)
    class_ids = [f"{c.name}@{c.version}" for c in classes]
    frozen = frozen_recipe(recipe, class_ids)
    rh = recipe_sha256(frozen)
    ctx, slots, quotas = build_context(recipe, classes, base_dir, recipe_hash=rh, counter=token_counter)

    kept: dict[int, list[dict]] = {}
    ledger, images, entries, no_draw, not_rendered, rounds = [], {}, [], 0, 0, 0
    # Everything the rounds depend on besides the recipe: a resume under a different generator, rules, renderer, token counter or
    # source file content is refused instead of mixing rounds.
    pins = [{"kind": k} | ({"sha256": sha} if (sha := getattr(src, "sha256", None)) else {}) for k, src in zip(ctx.source_kinds, ctx.sources, strict=True)]
    env = {
        "generator_version": __version__, "canon_versions": canon_versions(), "render_config": render_config(), "grammar_table_version": TABLE_VERSION,
        "token_estimator": {"custom": token_counter.__qualname__} if token_counter else {"fit": list(TOKEN_FIT), "cap": recipe.bounds.token_cap},
    }  # fmt: skip
    header = json.loads(json.dumps({"recipe_sha256": rh, "schema_version": SCHEMA_VERSION, "slots_planned": len(slots), "sources": pins, **env}))
    done = read_journal(out_dir, header) if (out_dir / JOURNAL).is_dir() else []
    for b in done:
        kept |= b["kept"]
        ledger += b["ledger"]
        images |= b["images"]
        entries += b["entries"]
        no_draw, not_rendered, rounds = no_draw + b["no_draw"], not_rendered + b["not_rendered"], rounds + 1
    for attempt in range(len(done), recipe.composition.attempt_cap):
        if not (todo := [s for s in slots if s.index not in kept]):
            break
        got, led, imgs, ent, nd, nr = _round(todo, attempt, ctx, recipe, rh, cache, max_parallel, batch_size)
        write_round(out_dir, header, attempt, got, led, imgs, ent, nd, nr)
        kept |= got
        ledger += led
        images |= imgs
        entries += ent
        no_draw, not_rendered, rounds = no_draw + nd, not_rendered + nr, rounds + 1

    samples = [r for i in sorted(kept) for r in kept[i]]
    short = shortfall(quotas, Counter(slots[i].error_class.name for i in kept))
    fonts = sorted({s.font for s, _ in ctx.styles})
    by_reason = Counter(r["reason"] for r in ledger)
    spec = recipe.source
    mutation = [p for p in (spec.parts if spec.kind == "mix" else (spec,)) if p.kind == "mutation"]
    meta = (base_dir / mutation[0].path).with_suffix(".meta.json") if mutation else None
    meta_bytes = meta.read_bytes() if meta and meta.is_file() else None  # the sidecar is not pinned by the recipe: record its sha256
    corpus = json.loads(meta_bytes).get("reference_crops") if meta_bytes else None
    balance = balance_report(samples)
    run_info = {
        "schema_version": SCHEMA_VERSION, **env, "seed": recipe.seed, "recipe": frozen, "recipe_sha256": rh,
        "classes": class_ids, "plugins": [m for m in reg.modules if m not in BUILTIN_MODULES], "entry_points": reg.entry_points,
        "styles": {
            s.name: {"font": s.font, "size": s.size, "packages": list(s.packages), "weight": w, "preamble_sha256": to_style(s).preamble_sha256}
            for s, w in ctx.styles
        },
        "pixel_policy_version": PIXEL_POLICY_VERSION,
        "numpy_version": np.__version__, "pillow_version": PIL.__version__,
        "quotas": quotas, "shortfall": short,
        "sources": [
            p | ({"rejected": dict(sorted(src.rejected.items()))} if k == "mutation" else {})
            for p, k, src in zip(pins, ctx.source_kinds, ctx.sources, strict=True)
        ],
        "mix_shares": list(spec.shares) if spec.kind == "mix" else [1.0],
        "scale": scale_report(samples, corpus=corpus), "balance": balance,
        "corpus_meta_sha256": hashlib.sha256(meta_bytes).hexdigest() if meta_bytes else None,
        "attempts": {"cap": recipe.composition.attempt_cap, "rounds": rounds},
        "counts": {
            "slots_planned": len(slots), "slots_kept": len(kept), "rows_kept": len(samples), "rows_dropped": len(ledger),
            "by_reason": dict(sorted(by_reason.items())), "no_draw": no_draw,
        },
        "alternates_not_rendered": not_rendered,
        "survival": (surv := survival(entries, [(cid, f) for cid, c in zip(class_ids, classes, strict=True) if quotas.get(c.name) for f in fonts])),
        "control_glyphs_used": control_glyphs_used(samples),
    }  # fmt: skip
    write_store(out_dir, samples, images, ledger, run_info)
    if "glyphfix" in recipe.export.formats:
        export_glyphfix(out_dir, out_dir / "glyphfix")
    shutil.rmtree(out_dir / JOURNAL, ignore_errors=True)
    return RunResult(out_dir, rh, len(slots), len(samples), len(ledger), surv, short, balance["warnings"])
