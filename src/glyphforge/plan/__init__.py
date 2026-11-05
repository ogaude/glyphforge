"""Composition planning: quotas, per-slot draws and multi-site composition."""

from glyphforge.plan.bounds import TOKEN_FIT, bounds_problem, est_tokens, nesting_depth, script_count, site_level
from glyphforge.plan.draw import PLAN_VERSION, build_context, draw_look, draw_slot, dress, plan_slots, wrapper_for
from glyphforge.plan.quota import SYNTH_BUCKET_ROWS, class_slots, largest_remainder, shortfall, spread, synthetic_paper_ids

__all__ = [
    "PLAN_VERSION", "SYNTH_BUCKET_ROWS", "TOKEN_FIT", "bounds_problem", "build_context", "class_slots", "draw_look", "draw_slot", "dress", "est_tokens",
    "largest_remainder", "nesting_depth", "plan_slots", "script_count", "shortfall", "site_level", "spread", "synthetic_paper_ids",
    "wrapper_for",
]  # fmt: skip
