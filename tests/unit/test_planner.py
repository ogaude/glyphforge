from __future__ import annotations

import dataclasses
import hashlib
import random
import re
from pathlib import Path

import pytest

from glyphforge.canon.safety import check_render
from glyphforge.errors import builtin_registry
from glyphforge.plan.bounds import est_tokens
from glyphforge.plan.draw import (
    MAX_DRAWS,
    PUNCT,
    TEXT_FRAGMENTS,
    DrawContext,
    Look,
    Slot,
    build_context,
    draw_look,
    draw_slot,
    dress,
    plan_slots,
    wrapper_for,
)
from glyphforge.recipe.load import effective_styles
from glyphforge.recipe.schema import BoundsSpec, CompositionSpec, Recipe, SourceSpec, StructureSpec, StyleSpec
from glyphforge.rng import slot_seed
from glyphforge.sources import Formula, ListSource, builtin_seed, load_source
from glyphforge.sources.grammar import GrammarSource

REG = builtin_registry()
UPS, PRIME = REG.get("greek.upsilon_v"), REG.get("primes.prime_l")
RH = "ab12cd34" + "0" * 56
STYLE = StyleSpec(name="default", font="cm", size=12)
LOOK = Look(STYLE, None, "display", None, None, None, None)


def _f(latex: str, **kw) -> Formula:
    return Formula(latex=latex, licence=kw.pop("licence", "CC0-1.0"), **kw)


def _slots(classes, total, source_kinds=("list",), first_share=1.0, **comp):
    return plan_slots(classes, CompositionSpec(total=total, **comp), source_kinds=source_kinds, first_share=first_share, recipe_hash=RH)


def _ctx(source, kind="list", *, kinds=None, bounds=None, counter=None, max_sites=1, seed=0, **struct) -> DrawContext:
    rec = Recipe(structure=StructureSpec(kinds=kinds or {"display": 1.0}, **struct))
    return DrawContext(
        seed,
        (source,),
        (kind,),
        (max_sites,),
        effective_styles(rec),
        rec.structure,
        rec.typography.site_levels,
        bounds or BoundsSpec(),
        counter,
    )


def _slot(i=0, cls=UPS, n_extra=0, paper_id=None) -> Slot:
    return Slot(i, cls, 0, n_extra, paper_id, "pid")


VS = ListSource(tuple(_f(s) for s in ("v+a", "v+b", "v-c", "2v+d", "v*e", "f+v")))


# --- plan_slots -------------------------------------------------------------------------------------------------------------------------


def test_quotas_by_largest_remainder_and_round_robin():
    a, b, c = (REG.get(n) for n in ("greek.upsilon_v", "greek.nu_v", "greek.iota_i"))
    slots, quotas = _slots([a, b, c], 10, shares={a.name: 0.5, b.name: 0.3, c.name: 0.2})
    assert quotas == {a.name: 5, b.name: 3, c.name: 2}
    assert [s.error_class.name for s in slots[:3]] == [a.name, b.name, c.name]
    assert sorted(s.error_class.name for s in slots) == sorted([a.name] * 5 + [b.name] * 3 + [c.name] * 2)
    assert _slots([a, b, c], 9)[1] == {a.name: 3, b.name: 3, c.name: 3}


def test_shares_unknown_and_missing_classes():
    with pytest.raises(ValueError, match="shares name unknown classes"):
        _slots([UPS], 4, shares={"nope": 1.0})
    _, quotas = _slots([UPS, PRIME], 4, shares={UPS.name: 1.0})
    assert quotas == {UPS.name: 4, PRIME.name: 0}


def test_source_interleave_is_exact():
    slots, _ = _slots([UPS], 10, source_kinds=("list", "list"), first_share=0.3)
    assert [s.index for s in slots if s.source == 0] == [3, 6, 9] and sum(s.source == 0 for s in slots) == 3
    assert {s.source for s in _slots([UPS], 10)[0]} == {0}


def test_source_mix_is_spread_per_class():
    slots, quotas = _slots([UPS, PRIME], 10, source_kinds=("list", "list"), first_share=0.5)
    for cls in (UPS, PRIME):
        mine = [s for s in slots if s.error_class.name == cls.name]
        assert abs(sum(s.source == 0 for s in mine) - 0.5 * quotas[cls.name]) <= 1 and {s.source for s in mine} == {0, 1}


def test_extra_control_counts():
    assert sum(s.n_extra for s in _slots([UPS], 10, hard_negative_ratio=1.5)[0]) == 5
    assert {s.n_extra for s in _slots([UPS], 10, hard_negative_ratio=1.0)[0]} == {0}
    assert {s.n_extra for s in _slots([UPS], 10, hard_negative_ratio=3)[0]} == {2}
    assert {s.n_extra for s in _slots([UPS], 10, hard_negative_ratio=1.5)[0]} <= {0, 1}
    assert sum(s.n_extra for s in _slots([UPS], 20, hard_negative_ratio=1.15)[0]) == 3  # floor(20 * 0.15), not float 0.1499...


def test_grammar_slots_get_synthetic_paper_ids_and_pair_ids():
    slots, _ = _slots([UPS], 40, source_kinds=("grammar",), hard_negative_ratio=1.5)
    assert all(re.fullmatch(f"synth:{RH[:8]}:\\d+", s.paper_id) for s in slots)
    rows: dict[str, int] = {}
    for s in slots:
        rows[s.paper_id] = rows.get(s.paper_id, 0) + 2 + s.n_extra
    assert max(rows.values()) <= 30 and len(rows) > 1
    assert slots[3].pair_id == hashlib.sha256(f"{RH}:3".encode()).hexdigest()[:16]
    assert {s.paper_id for s in _slots([UPS], 5)[0]} == {None}


# --- draw_look / dress ------------------------------------------------------------------------------------------------------------------


def test_text_fragments_fit_the_line_wrapper():
    assert 30 <= len(TEXT_FRAGMENTS) <= 50
    assert all(re.fullmatch(r"[A-Za-z0-9 ,.;:()'-]*", t) for t in TEXT_FRAGMENTS)


def test_draw_look_deterministic_and_attempt_dependent():
    rec = Recipe(structure=StructureSpec(kinds={"display": 1, "inline": 1, "numbered": 1}))
    styles = effective_styles(rec)
    a = draw_look(0, 7, 0, styles, rec.structure)
    assert a == draw_look(0, 7, 0, styles, rec.structure)
    assert any(draw_look(0, 7, k, styles, rec.structure) != a for k in range(1, 8))


def test_draw_look_tags_are_pure_digits_and_structure_specific():
    rec = Recipe(structure=StructureSpec(kinds={"display": 1, "inline": 1, "numbered": 1}, punct_prob=0.5))
    styles = effective_styles(rec)
    looks = [draw_look(1, i, 0, styles, rec.structure) for i in range(2000)]
    assert {lk.structure for lk in looks} == {"display", "inline", "numbered"}
    for lk in looks:
        if lk.structure == "numbered":
            assert re.fullmatch(r"^[1-9][0-9]?$", lk.tag) and lk.column_cm is not None
        else:
            assert lk.tag is None
        assert (lk.column_cm is None) == (lk.structure == "display")
        assert lk.structure == "inline" or (lk.before is None and lk.after is None)
        assert lk.before is None or lk.before in TEXT_FRAGMENTS
        assert lk.punct is None or lk.punct in PUNCT
    assert any(lk.punct for lk in looks) and any(lk.before for lk in looks)


def test_display_only_kinds_give_display_looks():
    rec = Recipe(structure=StructureSpec(kinds={"display": 1.0}))
    assert {draw_look(0, i, 0, effective_styles(rec), rec.structure).structure for i in range(50)} == {"display"}


def _look(structure="display", **kw) -> Look:
    return Look(
        STYLE,
        kw.pop("column_cm", None),
        structure,
        kw.pop("before", None),
        kw.pop("after", None),
        kw.pop("punct", None),
        kw.pop("tag", None),
    )


def test_dress():
    assert dress("x+1", _look(punct=",")) == "x+1,"
    assert dress("x+1.", _look(punct=".")) == "x+1."
    assert dress("x+1", _look("numbered", tag="3")) == "x+1\n\\tag{3}"
    assert dress("x+1", _look("numbered", tag="3", punct=".")) == "x+1.\n\\tag{3}"
    assert dress("x+1", _look("inline", before="where", punct=",")) == "where $x+1$ ,"
    assert dress("x+1", _look("inline")) == "$x+1$"
    assert dress("x+1", _look("inline", before="and", after="so")) == "and $x+1$ so"
    assert wrapper_for(_look()) == "display" and wrapper_for(_look("inline")) == wrapper_for(_look("numbered", tag="1")) == "line"


def test_dressing_never_creates_a_rejection():
    rec = Recipe(structure=StructureSpec(kinds={"display": 1, "inline": 1, "numbered": 1}, punct_prob=0.5))
    styles, seed = effective_styles(rec), builtin_seed()
    for i in range(200):
        look, body = draw_look(0, i, 0, styles, rec.structure), seed[i % len(seed)].latex
        if look.structure == "inline" and ("\\\\" in body or "&" in body):
            continue
        assert check_render(body) is None
        assert check_render(dress(body, look), wrapper_for(look)) is None, (look, body)


# --- draw_slot --------------------------------------------------------------------------------------------------------------------------


def test_load_source_grammar(tmp_path):
    assert isinstance(load_source(SourceSpec(kind="grammar", domains={"math": 1}), tmp_path), GrammarSource)


def test_draw_slot_is_deterministic_and_slot_pure():
    slot, other = _slot(5), [_slot(i) for i in range(5)]
    d = draw_slot(slot, 0, _ctx(ListSource(VS.items)))
    assert d is not None and d == draw_slot(slot, 0, _ctx(ListSource(VS.items)))
    ctx = _ctx(ListSource(VS.items))
    for s in other:
        draw_slot(s, 0, ctx)
    assert draw_slot(slot, 0, ctx) == d
    assert any(draw_slot(slot, a, _ctx(ListSource(VS.items))) != d for a in range(1, 8))


def test_draft_fields_for_a_display_slot():
    d = draw_slot(_slot(2), 0, _ctx(VS))
    assert d.wrapper == "display" and d.source_kind == "list" and d.n_sites == 1 and d.site_level == "base"
    assert d.target == d.variant.target and d.hard_negative == d.variant.hard_negative
    assert d.hard_negative in d.target_alternates and d.target in d.hard_negative_alternates
    assert d.n_tokens == est_tokens(d.target) and d.hard_negative_n_tokens == est_tokens(d.hard_negative) and d.controls == ()
    assert d.style.font == d.look.style.font and d.seed == draw_slot(_slot(2), 0, _ctx(VS)).seed


def test_multi_site_draft_reports_sites_and_levels():
    src = ListSource((_f("v+a_{v}+v^2"),))
    ds = [draw_slot(_slot(i), 0, _ctx(src, max_sites=3)) for i in range(30)]
    assert {d.n_sites for d in ds} == {1, 2, 3}
    assert all(d.site_level in ("base", "script") for d in ds)
    three = next(d for d in ds if d.n_sites == 3)
    assert three.target == r"\upsilon+a_{\upsilon}+\upsilon^2" and len(three.target_alternates) == 4


def test_numbered_drafts_add_untagged_alternates():
    d = draw_slot(_slot(1), 0, _ctx(VS, kinds={"numbered": 1.0}))
    assert d.wrapper == "line" and re.search(r"\n\\tag\{[1-9][0-9]?\}$", d.target)
    untagged = d.target.split("\n\\tag{")[0]
    assert untagged in d.target_alternates and d.hard_negative.split("\n\\tag{")[0] in d.hard_negative_alternates
    assert len(set(d.target_alternates)) == len(d.target_alternates) and d.target not in d.target_alternates


def test_inline_looks_take_single_line_bodies_only():
    multi = ListSource((_f("v&=1\\\\ w&=2", env="align*"),))
    assert draw_slot(_slot(), 0, _ctx(multi, kinds={"inline": 1.0})) is None
    assert draw_slot(_slot(), 0, _ctx(multi)) is not None
    d = draw_slot(_slot(), 0, _ctx(VS, kinds={"inline": 1.0}))
    assert d.target.count("$") == 2 and "\\\\" not in d.target


def test_over_cap_drafts_are_redrawn_never_rendered():
    long = _f("+".join(["v"] * 12))
    bounds = BoundsSpec(max_tokens=20, token_margin=0)
    assert est_tokens(long.latex) > 20
    assert draw_slot(_slot(), 0, _ctx(ListSource((long,)), bounds=bounds)) is None
    mixed = ListSource((long, _f("v+a")))
    d = draw_slot(_slot(), 0, _ctx(mixed, bounds=bounds))
    assert d is not None and est_tokens(d.target) <= 20 and d.formula.latex == "v+a"
    assert draw_slot(_slot(), 0, _ctx(ListSource((long,)), bounds=bounds, counter=lambda s: 0)) is not None


def test_extra_controls_match_style_bucket_and_differ():
    ctx = _ctx(VS, kinds={"numbered": 1.0}, punct_prob=1.0)
    d = draw_slot(_slot(3, n_extra=2), 0, ctx)
    assert d is not None and len(d.controls) == 2
    for j, c in enumerate(d.controls):
        assert c.index == j and c.formula.latex != d.formula.latex
        assert c.n_tokens // 16 == d.n_tokens // 16
        assert re.search(r"\n\\tag\{" + d.look.tag + r"\}$", c.label) and c.label.rstrip().endswith(f"\\tag{{{d.look.tag}}}")
        assert c.label.split("\n\\tag{")[0] in c.alternates and c.control_glyph
        assert c.site_level == "base"
        assert c.seed == slot_seed(ctx.seed, f"ctrl{j}", 3, 0) != d.seed


def test_extra_controls_are_distinct_rows():
    """WR-01: no control repeats an earlier control or the pair's hard negative (the builtin seed made 144/199 duplicates)."""
    ctx = _ctx(ListSource(builtin_seed()))
    drafts = [d for s in _slots([UPS, PRIME], 60, hard_negative_ratio=3)[0] if (d := draw_slot(s, 0, ctx))]
    assert drafts
    for d in drafts:
        labels = [d.target, d.hard_negative, *(c.label for c in d.controls)]
        assert len(d.controls) == 2 and len(set(labels)) == len(labels)


def test_control_label_is_the_hard_negative_side():
    d = draw_slot(_slot(0, n_extra=1), 0, _ctx(VS))
    c = d.controls[0]
    site = UPS.sites(c.formula.latex)[0]
    v = UPS.apply(c.formula.latex, site, random.Random(0))
    assert c.label in {v.hard_negative} | {
        UPS.apply(c.formula.latex, s, random.Random(0)).hard_negative for s in UPS.sites(c.formula.latex)
    }
    assert v.target in c.alternates


def test_no_control_found_means_no_draft():
    assert draw_slot(_slot(0, n_extra=1), 0, _ctx(ListSource((_f("v+a"),)))) is None


def test_mutation_controls_keep_their_attribution_and_grammar_controls_the_slot_id():
    cc = {"licence": "CC-BY-4.0", "paper_version": "v1", "authors": ("A. Author",)}
    src = ListSource((_f("v+a", paper_id="2401.0001", **cc), _f("v+b", paper_id="2401.0002", **cc), _f("v-c", paper_id="2401.0003", **cc)))
    d = draw_slot(_slot(0, n_extra=1), 0, _ctx(src, "mutation"))
    assert d.formula.paper_id.startswith("2401.") and d.controls[0].paper_id == d.controls[0].formula.paper_id
    assert d.controls[0].formula.authors == ("A. Author",) and d.controls[0].paper_id != d.formula.paper_id
    g = draw_slot(_slot(0, n_extra=1, paper_id="synth:ab12cd34:0"), 0, _ctx(GrammarSource({"math": 1.0}), "grammar"))
    assert g is not None and g.formula.paper_id == "synth:ab12cd34:0" == g.controls[0].paper_id == g.controls[0].formula.paper_id
    assert g.formula.licence == "CC0-1.0" and g.source_kind == "grammar"


def test_grammar_draws_the_requested_level():
    levels = {draw_slot(_slot(i), 0, _ctx(GrammarSource({"math": 1.0}), "grammar")).site_level for i in range(40)}
    assert levels <= {"base", "script", "scriptscript"} and len(levels) >= 2


def test_only_slot_rngs_are_used(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("forbidden rng primitive")

    for name in ("choice", "shuffle", "sample"):
        monkeypatch.setattr(random.Random, name, boom)
    assert draw_slot(_slot(1, n_extra=1), 0, _ctx(VS)) is not None
    assert draw_slot(_slot(1), 0, _ctx(GrammarSource({"math": 1.0}), "grammar")) is not None


def test_max_draws_is_bounded():
    assert MAX_DRAWS == 20


# --- build_context ----------------------------------------------------------------------------------------------------------------------


def test_build_context_list_and_mix(tmp_path):
    rec = Recipe(composition=CompositionSpec(total=6, hard_negative_ratio=2.0))
    ctx, slots, quotas = build_context(rec, [UPS, PRIME], Path(tmp_path), recipe_hash=RH)
    assert ctx.source_kinds == ("list",) and ctx.max_sites == (1,) and len(slots) == 6 and quotas == {UPS.name: 3, PRIME.name: 3}
    assert all(s.n_extra == 1 for s in slots)
    mix = Recipe(source=SourceSpec(kind="mix", parts=(SourceSpec(kind="grammar"), SourceSpec(kind="builtin")), shares=(0.3, 0.7)))
    ctx, slots, _ = build_context(mix, [UPS], Path(tmp_path), recipe_hash=RH)
    assert ctx.source_kinds == ("grammar", "list") and isinstance(ctx.sources[0], GrammarSource)
    assert sum(s.source == 0 for s in slots) == 30 and all((s.paper_id is None) == (s.source == 1) for s in slots)
    d = draw_slot(slots[0], 0, ctx)
    assert d is None or d.source_kind in ("grammar", "list")


def test_grammar_drafts_stay_at_the_drawn_site_level():
    """WR-06: with site_levels {script: 1} no grammar draft may mutate a base-level site (5/600 did when only sites[0] was checked)."""
    ctx = dataclasses.replace(_ctx(GrammarSource(), "grammar"), site_levels={"base": 0.0, "script": 1.0, "scriptscript": 0.0})
    drafts = [d for s in _slots([REG.get(n) for n in REG.names()], 300, source_kinds=("grammar",))[0] if (d := draw_slot(s, 0, ctx))]
    assert len(drafts) > 200 and {d.site_level for d in drafts} == {"script"}
