"""Per-slot planning: slot allocation, typography/structure draws, source draws and label dressing (D-10..D-21a)."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

from glyphforge.canon import canonical
from glyphforge.canon.safety import check_render
from glyphforge.plan.bounds import bounds_problem, est_tokens, site_level
from glyphforge.plan.compose import choose_sites, compose
from glyphforge.plan.quota import class_slots, largest_remainder, spread, synthetic_paper_ids
from glyphforge.rng import pick, slot_rng, slot_seed

if TYPE_CHECKING:
    from glyphforge.errors.api import ErrorClass, Site, Variant
    from glyphforge.export.leak import Blocklist
    from glyphforge.recipe.schema import BoundsSpec, CompositionSpec, Recipe, StructureSpec, StyleSpec
    from glyphforge.render.style import Style
    from glyphforge.sources.base import DrawSource, Formula

# Plain connectives; every entry stays inside the "line" wrapper text set [A-Za-z0-9 ,.;:()'-].
TEXT_FRAGMENTS = (
    "where", "and", "for all", "with", "is given by", "such that", "then", "we have", "since", "hence", "if", "so that", "for", "as",
    "denotes", "satisfies", "becomes", "yields", "implies", "holds for", "defined by", "in terms of", "for some", "for each",
    "it follows that", "note that", "let", "assume", "consider", "set", "which gives", "thus", "where we used", "whenever", "while",
    "so", "or", "but", "because", "and hence", "and so", "given that",
)  # fmt: skip
PUNCT = (",", ".", ";")
MAX_DRAWS = 20
PLAN_VERSION = "2"  # bump when slot planning changes; 2 = exact global mix split
_LEVELS = ("base", "script", "scriptscript")
_TAG_SPLIT = "\n\\tag{"


@dataclass(frozen=True)
class Look:
    style: StyleSpec
    column_cm: float | None
    structure: str
    before: str | None
    after: str | None
    punct: str | None
    tag: str | None


@dataclass(frozen=True)
class Slot:
    index: int
    error_class: ErrorClass
    source: int
    n_extra: int
    paper_id: str | None
    pair_id: str


@dataclass(frozen=True)
class Control:
    index: int
    formula: Formula
    label: str
    alternates: tuple[str, ...]
    control_glyph: str
    n_tokens: int
    site_level: str
    paper_id: str | None
    seed: int


@dataclass(frozen=True)
class Draft:
    slot: Slot
    attempt: int
    look: Look
    wrapper: str
    style: Style
    formula: Formula
    source_kind: str
    n_sites: int
    site_level: str
    variant: Variant
    target: str
    hard_negative: str
    target_alternates: tuple[str, ...]
    hard_negative_alternates: tuple[str, ...]
    n_tokens: int
    hard_negative_n_tokens: int
    seed: int
    controls: tuple[Control, ...]


@dataclass(frozen=True)
class DrawContext:
    seed: int
    sources: tuple[DrawSource, ...]
    source_kinds: tuple[str, ...]
    max_sites: tuple[int, ...]
    styles: tuple[tuple[StyleSpec, float], ...]
    structure: StructureSpec
    site_levels: Mapping[str, float]
    bounds: BoundsSpec
    counter: Callable[[str], int] | None
    blocklist: Blocklist | None = None


def plan_slots(
    classes: Sequence[ErrorClass], composition: CompositionSpec, *, source_kinds: Sequence[str], first_share: float, recipe_hash: str
) -> tuple[list[Slot], dict[str, int]]:
    """Exact per-class quotas (largest remainder), round-robin class order and extra-control counts.

    A mix splits exactly over the whole run (largest remainder of the total), then over classes (largest remainder of that count by quota),
    then each class interleaves its own first-source slots with Bresenham spreading so classes never alias with sources.
    """
    names = [c.name for c in classes]
    shares = composition.shares if composition.shares is not None else dict.fromkeys(names, 1.0)
    if unknown := sorted(set(shares) - set(names)):
        raise ValueError(f"shares name unknown classes: {unknown}")
    quotas = largest_remainder(composition.total, {n: shares.get(n, 0.0) for n in names})
    by_name = {c.name: c for c in classes}
    order = class_slots(quotas)
    mix = len(source_kinds) > 1
    first = Fraction(str(first_share))
    owed = largest_remainder(largest_remainder(composition.total, {"0": first, "1": 1 - first})["0"], quotas) if mix else {}
    seen: dict[str, int] = dict.fromkeys(names, 0)
    src = []
    for n in order:
        src.append(0 if not mix or spread(seen[n], Fraction(owed[n], quotas[n])) else 1)
        seen[n] += 1
    rate = Fraction(str(composition.hard_negative_ratio)) - 1  # 1.15 - 1 in floats is 0.1499..., which undershoots the prefix sums
    extra = [spread(i, rate) for i in range(len(order))]
    grammar = [i for i, s in enumerate(src) if source_kinds[s] == "grammar"]
    ids = dict(zip(grammar, synthetic_paper_ids([2 + extra[i] for i in grammar], f"synth:{recipe_hash[:8]}"), strict=True))
    slots = [
        Slot(i, by_name[n], src[i], extra[i], ids.get(i), hashlib.sha256(f"{recipe_hash}:{i}".encode()).hexdigest()[:16])
        for i, n in enumerate(order)
    ]
    return slots, quotas


def _fragment(rng: random.Random) -> str:
    return TEXT_FRAGMENTS[int(rng.random() * len(TEXT_FRAGMENTS))]


def draw_look(seed: int, slot: int, attempt: int, styles: Sequence[tuple[StyleSpec, float]], structure: StructureSpec) -> Look:
    """Typography and structure for one (slot, attempt).

    The style comes from stage "style" (one pick). Everything else comes from stage "structure" in a fixed order: kind, column width
    (inline and numbered only), tag (numbered only, pure digits 1-99), before and after text (inline only, probabilities text_prob and
    text_prob / 2), punctuation (probability punct_prob).
    """
    style = pick(slot_rng(seed, "style", slot, attempt), [s for s, _ in styles], [w for _, w in styles])
    rng = slot_rng(seed, "structure", slot, attempt)
    kinds, cols = sorted(structure.kinds), sorted(structure.column_cm)
    kind = pick(rng, kinds, [structure.kinds[k] for k in kinds])
    column = pick(rng, cols, [structure.column_cm[c] for c in cols]) if kind != "display" else None
    tag = str(1 + int(rng.random() * 99)) if kind == "numbered" else None
    before = after = None
    if kind == "inline":
        before = _fragment(rng) if rng.random() < structure.text_prob else None
        after = _fragment(rng) if rng.random() < structure.text_prob / 2 else None
    punct = PUNCT[int(rng.random() * len(PUNCT))] if rng.random() < structure.punct_prob else None
    return Look(style, column, kind, before, after, punct, tag)


def dress(body: str, look: Look) -> str:
    """Native LightOnOCR style: display body plus trailing punctuation, numbered adds a final ``\\tag`` line, inline wraps in ``$``."""
    body = body.strip()
    punct = None if body.endswith(PUNCT) else look.punct  # a body that already ends in punctuation gets no second mark
    if look.structure == "inline":
        return " ".join(p for p in (look.before, f"${body}$", punct, look.after) if p)
    if punct:
        body += punct
    return f"{body}{_TAG_SPLIT}{look.tag}}}" if look.tag else body


def wrapper_for(look: Look) -> str:
    return "display" if look.structure == "display" else "line"


def _labels(v: Variant, look: Look) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """Dressed (target, hard negative, target alternates, hard-negative alternates); numbered looks add the untagged label (D-21a)."""

    def alts(label: str, others: Sequence[str]) -> tuple[str, ...]:
        out = [dress(o, look) for o in others] + ([label.split(_TAG_SPLIT)[0]] if look.tag else [])
        return tuple(a for a in dict.fromkeys(out) if a != label)

    t, h = dress(v.target, look), dress(v.hard_negative, look)
    return t, h, alts(t, (v.hard_negative, *v.target_alternates)), alts(h, (v.target, *v.hard_negative_alternates))


def _level(latex: str, sites: Sequence[Site]) -> str:
    return max((site_level(latex, s) for s in sites), key=_LEVELS.index)


def _formula(slot: Slot, ctx: DrawContext, look: Look, rng: random.Random) -> Formula | None:
    """Grammar sources get the drawn script level and multiline share; list and mutation sources are never forced (D-17)."""
    src, cls = ctx.sources[slot.source], slot.error_class
    if ctx.source_kinds[slot.source] != "grammar":
        return src.draw(cls, rng)
    levels = sorted(ctx.site_levels)
    level = pick(rng, levels, [ctx.site_levels[k] for k in levels])
    return src.draw(cls, rng, level=level, multiline=rng.random() < ctx.structure.multiline and look.structure != "inline")


def _problem(label: str, look: Look, ctx: DrawContext) -> str | None:
    b = ctx.bounds
    return check_render(label, wrapper_for(look)) or bounds_problem(
        label, max_tokens=b.token_cap, max_depth=b.max_depth, max_scripts=b.max_scripts, counter=ctx.counter
    )


def _pair(
    slot: Slot,
    ctx: DrawContext,
    look: Look,
    src_rng: random.Random,
    site_rng: random.Random,
    max_sites: int,
    accept: Callable[[Formula, str], bool],
):
    """First formula within bounds that ``accept`` allows: (formula, chosen sites, variant, labels), or None after MAX_DRAWS draws."""
    cls = slot.error_class
    for _ in range(MAX_DRAWS):
        f = _formula(slot, ctx, look, src_rng)
        if f is None or (look.structure == "inline" and ("\\\\" in f.latex or "&" in f.latex)) or not (sites := cls.sites(f.latex)):
            continue
        chosen = choose_sites(sites, max_sites, src_rng)
        v = compose(f.latex, cls, chosen, site_rng)
        labels = _labels(v, look)
        if (
            not any(_problem(x, look, ctx) for x in labels[:2])
            and not (ctx.blocklist and (ctx.blocklist.match(labels[0], canonical(f.latex), f.paper_id) or ctx.blocklist.match(labels[1], None, None)))
            and accept(f, labels[1])
        ):
            return f, chosen, v, labels
    return None


def draw_slot(slot: Slot, attempt: int, ctx: DrawContext) -> Draft | None:
    """The Draft for (slot, attempt), or None when no formula within bounds (or no matching control) was found. Slot-pure."""
    from glyphforge.recipe.load import to_style  # lazy: keeps plan/ free of pydantic at import time

    i, cls, count = slot.index, slot.error_class, ctx.counter or est_tokens
    look = draw_look(ctx.seed, i, attempt, ctx.styles, ctx.structure)
    got = _pair(
        slot,
        ctx,
        look,
        slot_rng(ctx.seed, "source", i, attempt),
        slot_rng(ctx.seed, "site", i, attempt),
        ctx.max_sites[slot.source],
        lambda *_: True,
    )
    if got is None:
        return None
    f, chosen, v, (t, h, t_alts, h_alts) = got
    n_sites = int(dict(v.meta).get("n_sites", 1))
    own = chosen[len(chosen) - n_sites :]
    n_tokens, controls, used = count(t), [], {t, h}  # a control repeating the pair or an earlier control would be a duplicate row
    for j in range(slot.n_extra):
        cseed = slot_seed(ctx.seed, f"ctrl{j}", i, attempt)
        rng = random.Random(cseed)
        c = _pair(slot, ctx, look, rng, rng, 1, lambda g, label: g.latex != f.latex and label not in used and count(label) // 16 == n_tokens // 16)
        if c is None:
            return None
        cf, csites, cv, (_, ch, _, c_alts) = c
        used.add(ch)
        cf = _own(cf, slot)
        controls.append(Control(j, cf, ch, c_alts, cv.control_glyph, count(ch), _level(cf.latex, csites), cf.paper_id, cseed))
    return Draft(
        slot, attempt, look, wrapper_for(look), to_style(look.style, cls.packages, look.column_cm), _own(f, slot),
        ctx.source_kinds[slot.source], n_sites, _level(f.latex, own), v, t, h, t_alts, h_alts, n_tokens, count(h),
        slot_seed(ctx.seed, "site", i, attempt), tuple(controls),
    )  # fmt: skip


def _own(f: Formula, slot: Slot) -> Formula:
    """Grammar formulas carry the slot's synthetic paper id; mutation formulas keep their own attribution."""
    return f.model_copy(update={"paper_id": slot.paper_id}) if slot.paper_id else f


def build_context(
    recipe: Recipe,
    classes: Sequence[ErrorClass],
    base_dir: Path,
    *,
    recipe_hash: str,
    counter: Callable[[str], int] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[DrawContext, list[Slot], dict[str, int]]:
    """Open the recipe's sources (a mix opens both parts in order), plan the slots and pre-build each list or mutation source's class indices."""
    from glyphforge.export.leak import load_blocklist
    from glyphforge.recipe.load import effective_styles  # lazy: keeps plan/ free of pydantic at import time
    from glyphforge.sources.listing import load_source

    spec = recipe.source
    parts = spec.parts if spec.kind == "mix" else (spec,)
    kinds = tuple({"grammar": "grammar", "mutation": "mutation"}.get(p.kind, "list") for p in parts)
    ctx = DrawContext(
        recipe.seed, tuple(load_source(p, base_dir) for p in parts), kinds, tuple((p.max_sites or 2) if p.kind == "mutation" else 1 for p in parts),
        effective_styles(recipe), recipe.structure, recipe.typography.site_levels, recipe.bounds, counter,
        load_blocklist(recipe.export.blocklist, base_dir) if recipe.export.blocklist else None,
    )  # fmt: skip
    slots, quotas = plan_slots(
        classes, recipe.composition, source_kinds=kinds, first_share=spec.shares[0] if spec.kind == "mix" else 1.0, recipe_hash=recipe_hash
    )
    for k, src in enumerate(ctx.sources):
        if kinds[k] != "grammar":
            src.index(list({s.error_class.name: s.error_class for s in slots if s.source == k}.values()), progress)
    return ctx, slots, quotas
