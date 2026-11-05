"""Thin command line shell; all logic lives in the library."""

from __future__ import annotations

import sys


def main() -> None:
    try:
        import typer  # noqa: F401
    except ImportError:
        print(
            "glyphforge CLI needs the [cli] extra: pip install 'glyphforge[cli]' (or run: python -m glyphforge.render.doctor)",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    from glyphforge._cli import build_app

    build_app()()
