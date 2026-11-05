"""Thin command line shell; all logic lives in the library."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    try:
        import typer
    except ImportError:
        print(
            "glyphforge CLI needs the [cli] extra: pip install 'glyphforge[cli]' (or run: python -m glyphforge.render.doctor)",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    from glyphforge.render.doctor import run_checks

    app = typer.Typer(no_args_is_help=True)
    app.callback()(lambda: None)  # keeps `doctor` a named subcommand while it is the only one

    @app.command()
    def doctor(pull: bool = typer.Option(False, "--pull", help="docker pull the pinned image first")) -> None:
        """Check Docker, the pinned image, font packages, memory and the cache directory."""
        results = run_checks(pull=pull)
        for c in results:
            typer.echo(f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        if not all(c.ok for c in results):
            raise typer.Exit(1)

    @app.command()
    def snapshot(glyphfix_root: Path, out: Path) -> None:
        """Freeze glyphfix-math training rows into a pinned mutation snapshot."""
        from glyphforge.sources.mutation import build_snapshot

        meta = build_snapshot(glyphfix_root, out)
        typer.echo(f"sha256 {meta['sha256']}")
        typer.echo(f"rows {meta['rows']}")

    app()
