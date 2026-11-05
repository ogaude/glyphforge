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
    "export_store": "glyphforge.export",
    "export_glyphfix": "glyphforge.export",
    "export_parquet": "glyphforge.export",
    "leak_check": "glyphforge.export.leak",
    "build_blocklist": "glyphforge.export.leak",
    "LeakError": "glyphforge.export.leak",
    "degrade_ops": "glyphforge.degrade",
    "apply_ops": "glyphforge.degrade",
    "plan_run": "glyphforge.pipeline",
    "preview_html": "glyphforge.preview",
    "preview_recipe": "glyphforge.preview",
    "validate_recipe": "glyphforge.validate",
    "check_store": "glyphforge.validate",
}
__all__ = [
    "CommandPair",
    "ConfusionPair",
    "ErrorClass",
    "LeakError",
    "Recipe",
    "RunResult",
    "__version__",
    "apply_ops",
    "build_blocklist",
    "check_error_class",
    "check_store",
    "degrade_ops",
    "export_glyphfix",
    "export_parquet",
    "export_store",
    "leak_check",
    "load_recipe",
    "pairs_from_alignment",
    "plan_run",
    "preview_html",
    "preview_recipe",
    "register",
    "run",
    "validate_recipe",
]


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module 'glyphforge' has no attribute {name!r}")
    return getattr(importlib.import_module(_LAZY[name]), name)
