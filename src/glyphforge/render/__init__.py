"""Rendering: sandboxed pdflatex batches, rasterization and ink-crop comparison."""

from __future__ import annotations

from glyphforge.canon.safety import FILTER_VERSION, WRAP_VERSION, WRAPPERS, check_safe, wrap
from glyphforge.render.batch import PairResult, render_equivalence, render_many
from glyphforge.render.cache import STATUSES, RenderResult, cache_key, compare, load_bitmap, render_config
from glyphforge.render.docker import (
    IMAGE,
    IMAGE_DIGEST,
    PREAMBLE,
    PREAMBLE_SHA256,
    RenderInfrastructureError,
    docker_available,
    docker_diagnosis,
)
from glyphforge.render.raster import INK_THRESHOLD, RENDER_DPI, TOLERANCE_VERSION, compare_arrays, ink_crop, ink_overflows
from glyphforge.render.style import DEFAULT_STYLE, FONT_BLOCKS, Style

__all__ = [
    "DEFAULT_STYLE", "FILTER_VERSION", "FONT_BLOCKS", "IMAGE", "IMAGE_DIGEST", "INK_THRESHOLD", "PREAMBLE", "PREAMBLE_SHA256", "RENDER_DPI",
    "STATUSES", "TOLERANCE_VERSION", "WRAPPERS", "WRAP_VERSION", "PairResult", "RenderInfrastructureError", "RenderResult", "Style",
    "cache_key", "check_safe", "compare", "compare_arrays", "docker_available", "docker_diagnosis", "ink_crop", "ink_overflows",
    "load_bitmap", "render_config", "render_equivalence", "render_many", "wrap",
]
