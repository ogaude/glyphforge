from __future__ import annotations

import os
from pathlib import Path


def cache_dir() -> Path:
    env = os.environ.get("GLYPHFORGE_CACHE")
    if env:
        p = Path(env)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        p = Path(base) / "glyphforge"
    p.mkdir(parents=True, exist_ok=True)
    return p
