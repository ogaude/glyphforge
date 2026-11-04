import inspect

import pytest

import glyphforge.canon
import glyphforge.render

RENDER_NAMES = [
    "render_many", "render_equivalence", "PairResult", "RenderResult", "RenderInfrastructureError", "STATUSES", "cache_key", "render_config",
    "load_bitmap", "compare", "compare_arrays", "ink_crop", "ink_overflows", "check_safe", "wrap", "WRAPPERS", "WRAP_VERSION", "FILTER_VERSION",
    "TOLERANCE_VERSION", "RENDER_DPI", "INK_THRESHOLD", "IMAGE", "IMAGE_DIGEST", "PREAMBLE", "PREAMBLE_SHA256", "docker_available",
    "docker_diagnosis", "Style", "DEFAULT_STYLE", "FONT_BLOCKS",
]
CANON_NAMES = ["canonical", "canonicalize", "check_safe", "wrap", "tokenize", "detokenize", "WRAPPERS", "WRAP_VERSION", "FILTER_VERSION", "NORMALIZE_RULES_VERSION"]


@pytest.mark.parametrize("name", RENDER_NAMES)
def test_render_names(name):
    assert hasattr(glyphforge.render, name)


@pytest.mark.parametrize("name", CANON_NAMES)
def test_canon_names(name):
    assert hasattr(glyphforge.canon, name)


def test_signatures():
    r = glyphforge.render
    params = inspect.signature(r.render_many).parameters
    assert list(params) == ["latex_list", "batch_size", "cache", "timeout_s", "max_parallel", "wrapper", "style"]
    assert params["style"].kind is inspect.Parameter.KEYWORD_ONLY and params["style"].default is None
    assert list(inspect.signature(r.cache_key).parameters) == ["latex", "wrapper", "style"]
    assert list(inspect.signature(r.render_equivalence).parameters) == ["gt", "pred", "render_kwargs"]
