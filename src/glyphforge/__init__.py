from __future__ import annotations

import importlib
import importlib.metadata

__version__ = importlib.metadata.version("glyphforge")

_LAZY = {
    "run": "glyphforge.pipeline",
    "RunResult": "glyphforge.pipeline",
    "Recipe": "glyphforge.recipe",
    "load_recipe": "glyphforge.recipe",
    "register": "glyphforge.errors",
    "ConfusionPair": "glyphforge.errors",
    "CommandPair": "glyphforge.errors",
    "ErrorClass": "glyphforge.errors",
    "check_error_class": "glyphforge.errors",
    "pairs_from_alignment": "glyphforge.errors",
}
__all__ = [
    "CommandPair", "ConfusionPair", "ErrorClass", "Recipe", "RunResult", "__version__", "check_error_class", "load_recipe",
    "pairs_from_alignment", "register", "run",
]


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module 'glyphforge' has no attribute {name!r}")
    return getattr(importlib.import_module(_LAZY[name]), name)
