"""Write (or with --check, verify) the published recipe JSON Schema."""

from __future__ import annotations

import sys
from pathlib import Path

from glyphforge.validate import schema_text

PATH = Path(__file__).parents[1] / "src/glyphforge/recipe/schema.json"


def main() -> int:
    text = schema_text()
    if "--check" in sys.argv:
        return 0 if PATH.read_text(encoding="utf-8") == text else 1
    PATH.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
