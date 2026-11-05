"""Composition planning: quotas, per-slot draws and multi-site composition."""

from glyphforge.plan.bounds import TOKEN_FIT, bounds_problem, est_tokens, nesting_depth, script_count, site_level
from glyphforge.plan.quota import SYNTH_BUCKET_ROWS, class_slots, largest_remainder, shortfall, spread, synthetic_paper_ids

__all__ = [
    "SYNTH_BUCKET_ROWS", "TOKEN_FIT", "bounds_problem", "class_slots", "est_tokens", "largest_remainder", "nesting_depth", "script_count",
    "shortfall", "site_level", "spread", "synthetic_paper_ids",
]
