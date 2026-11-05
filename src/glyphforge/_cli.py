"""The Typer app behind ``glyphforge``: every command is a thin shell over a library function.

Library imports stay inside command bodies so start-up never loads pyarrow or datasets, and so ``--docker-memory`` can set its environment
variable before ``glyphforge.resources`` reads it.
"""

import functools
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

MaxWorkers = Annotated[
    int | None, typer.Option("--max-workers", min=1, help="Parallel Docker renders (operational only; never changes the output).")
]
DockerMemory = Annotated[int | None, typer.Option("--docker-memory", min=1, help="Docker memory cap per render, in GB (operational only).")]
Cache = Annotated[Path | None, typer.Option("--cache", help="Render cache directory (operational only).")]
BatchSize = Annotated[
    int, typer.Option("--batch-size", min=1, help="Formulas per Docker batch (operational only; never changes the output).")
]
AsJson = Annotated[bool, typer.Option("--json", help="Machine-readable output on stdout.")]


def _env(docker_memory: int | None) -> None:
    """Must run before the first import of glyphforge.resources, which reads the variable at import time."""
    if docker_memory is not None:
        os.environ["GLYPHFORGE_DOCKER_MEMORY_GB"] = str(docker_memory)


def _hits(hits: list[dict], as_json: bool = False) -> None:
    if as_json:
        typer.echo(json.dumps(hits, indent=2))
    for h in [] if as_json else hits:
        typer.echo(f"leak {h['sample_id']} {h['pair_id']} {h['reason']} {h['entry']}")


def _code(exc: Exception) -> int | None:
    """Exit code for a known failure (D-28), None for anything unexpected."""
    from pydantic import ValidationError

    from glyphforge.render import RenderInfrastructureError

    if isinstance(exc, ValidationError):
        return 2
    if isinstance(exc, FileExistsError | FileNotFoundError):
        return 2
    if isinstance(exc, RenderInfrastructureError | OSError) or (isinstance(exc, ValueError) and "sha256 mismatch" in str(exc)):
        return 1
    return 2 if isinstance(exc, ValueError) else None


def _exits(fn):
    """The single exception-to-exit-code mapping: leak hit and infrastructure failures exit 1, usage and validation errors exit 2."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except typer.Exit:
            raise
        except Exception as exc:
            from glyphforge.export.leak import LeakError

            if isinstance(exc, LeakError):
                _hits(exc.hits)
                raise typer.Exit(1) from None
            if (code := _code(exc)) is None:
                raise
            from pydantic import ValidationError

            from glyphforge.validate import field_errors

            for line in field_errors(exc) if isinstance(exc, ValidationError) else [str(exc)]:
                typer.echo(line, err=True)
            raise typer.Exit(code) from None

    return wrapper


def build_app() -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, add_completion=False)

    @app.command()
    @_exits
    def run(
        recipe: Path,
        out: Path,
        no_export: Annotated[bool, typer.Option("--no-export", help="Stop after the store; skip the auto-export.")] = False,
        max_workers: MaxWorkers = None,
        docker_memory: DockerMemory = None,
        cache: Cache = None,
        batch_size: BatchSize = 100,
    ) -> None:
        """Run RECIPE into OUT, then export OUT/export/<format> for each format the recipe lists.

        Resumes a matching journal in OUT; refuses (exit 2) an OUT that already holds run.json or a journal of another recipe. The recipe's
        export.blocklist path resolves against the recipe file's directory and its pinned sha256 is always verified; a blocklist hit
        exits 1 and leaves the store complete.
        """
        _env(docker_memory)
        from rich.progress import Progress

        from glyphforge.pipeline import run as run_recipe

        with Progress(console=Console(stderr=True), transient=True) as bar:
            task = bar.add_task("slots", total=None)
            res = run_recipe(
                recipe, out, cache=cache, max_parallel=max_workers, batch_size=batch_size, export=not no_export,
                progress=lambda stage, done, total: bar.update(task, description=stage, completed=done, total=total),
            )  # fmt: skip
        typer.echo(f"recipe_sha256 {res.recipe_sha256}")
        typer.echo(f"rows kept {res.rows_kept} dropped {res.rows_dropped} slots {res.slots_planned}")
        for d in sorted((out / "export").glob("*")) if (out / "export").is_dir() else ():
            typer.echo(f"export {d}")
        if res.shortfall.get("short_total"):
            typer.echo(f"shortfall: {res.shortfall['short_total']} slot(s) short in {res.shortfall['short_classes']}", err=True)
        for w in res.warnings:
            typer.echo(f"warning: {w}", err=True)

    @app.command()
    @_exits
    def plan(recipe: Path, as_json: AsJson = False, max_workers: MaxWorkers = None, docker_memory: DockerMemory = None) -> None:
        """Dry run: quota table, totals, recipe hash and a rough wall-time and memory estimate. No Docker, nothing written."""
        _env(docker_memory)
        from rich.progress import Progress
        from rich.table import Table

        from glyphforge.pipeline import plan_run

        with Progress(console=Console(stderr=True), transient=True) as bar:
            task = bar.add_task("index", total=None)
            p = plan_run(
                recipe, base_dir=recipe.resolve().parent, max_parallel=max_workers,
                progress=lambda stage, done, total: bar.update(task, description=stage, completed=done, total=total),
            )  # fmt: skip
        if as_json:
            typer.echo(json.dumps(p))
            return
        table = Table("class", "source", "pairs", "extra controls")
        for q in p["quotas"]:
            table.add_row(q["error_class"], q["source"], str(q["pairs"]), str(q["extra_controls"]))
        Console().print(table)
        typer.echo(f"recipe_sha256 {p['recipe_sha256']}")
        typer.echo(" ".join(f"{k} {v}" for k, v in p["totals"].items()) + f" attempt_cap {p['attempt_cap']}")
        e = p["estimate"]
        typer.echo(f"estimate (rough): {e['workers']} worker(s), {e['memory_gb']} GB, ~{e['wall_s']} s; {e['basis']}")

    @app.command()
    @_exits
    def validate(
        recipe: Path,
        store: Annotated[Path | None, typer.Option("--store", help="Also check this store directory's integrity.")] = None,
        schema: Annotated[Path | None, typer.Option("--schema", help="Write the recipe JSON Schema to this file.")] = None,
        as_json: AsJson = False,
    ) -> None:
        """Check RECIPE without Docker: schema errors by field path (exit 2), class resolution, pinned-file sha256 (mismatch exits 1)."""
        from glyphforge.fileio import atomic_write
        from glyphforge.validate import check_store, schema_text, validate_recipe

        if schema:
            atomic_write(schema, schema_text().encode("utf-8"))
        res = validate_recipe(recipe)
        if store:
            res["store_problems"] = check_store(store)
        problems = [*res["problems"], *res.get("store_problems", [])]
        if as_json:
            typer.echo(json.dumps(res))
        else:
            typer.echo(
                f"{'ok' if not problems else 'FAIL'} recipe_sha256 {res['recipe_sha256']} classes {len(res['classes'])} pins {len(res['pins'])}"
            )
            for line in problems:
                typer.echo(line, err=True)
        if problems:
            raise typer.Exit(1)

    @app.command()
    @_exits
    def export(
        store: Path,
        out: Path,
        recipe: Annotated[
            Path | None, typer.Option("--recipe", help="Take only this file's export section instead of the store's frozen one.")
        ] = None,
        fmt: Annotated[str | None, typer.Option("--format", help="glyphfix or parquet; default is the store's frozen format list.")] = None,
        as_json: AsJson = False,
    ) -> None:
        """Export STORE to OUT/<format> with the leak gate always run first.

        Uses the store's frozen export section; --recipe takes only the export section of another file (recorded in the manifest). The
        blocklist path resolves against the --recipe file's directory, else against the current directory; its pinned sha256 is always
        verified. A leak hit prints the hit report and exits 1 with nothing written.
        """
        from glyphforge.export import export_store
        from glyphforge.recipe import load_recipe

        run_json = json.loads((store / "run.json").read_text(encoding="utf-8"))
        formats = [fmt] if fmt else run_json["recipe"]["export"]["formats"]
        if not formats:
            raise ValueError("no export format: pass --format or use a store whose recipe lists export.formats")
        spec, base = (load_recipe(recipe).export, recipe.resolve().parent) if recipe else (None, None)
        manifests = []
        try:
            for f in formats:
                manifests.append(export_store(store, out / f, f, spec=spec, base_dir=base))
        except Exception as exc:
            if as_json and (hits := getattr(exc, "hits", None)):
                _hits(hits, True)
                raise typer.Exit(1) from None
            raise
        if as_json:
            typer.echo(json.dumps(manifests))
        for f, m in zip(formats, manifests, strict=True):
            if not as_json:
                typer.echo(f"export {out / f} rows {m['n_rows']} blocklist_sha256 {m['blocklist']['sha256']}")

    @app.command()
    @_exits
    def preview(
        source: Path,
        out: Path,
        pairs: Annotated[int, typer.Option("--pairs", min=1, help="Minimal pairs to show.")] = 48,
        max_workers: MaxWorkers = None,
        docker_memory: DockerMemory = None,
        cache: Cache = None,
        batch_size: BatchSize = 100,
    ) -> None:
        """Write a self-contained HTML contact sheet from SOURCE, a store directory (no rendering) or a recipe file (renders a small run)."""
        _env(docker_memory)
        from glyphforge.fileio import atomic_write
        from glyphforge.preview import preview_html, preview_recipe

        if (source / "run.json").is_file():
            html = preview_html(source, pairs=pairs)
        else:
            html = preview_recipe(source, pairs=pairs, cache=cache, max_parallel=max_workers, batch_size=batch_size)
        atomic_write(out, html.encode("utf-8"))
        typer.echo(str(out))

    @app.command()
    @_exits
    def blocklist(glyphfix_root: Path, out: Path) -> None:
        """Build the pinned leak blocklist from glyphfix-math's eval and test data."""
        from glyphforge.export.leak import build_blocklist

        meta = build_blocklist(glyphfix_root, out)
        typer.echo(f"sha256 {meta['sha256']}")
        for k, n in meta["counts"].items():
            typer.echo(f"{k} {n}")

    @app.command()
    @_exits
    def snapshot(glyphfix_root: Path, out: Path) -> None:
        """Freeze glyphfix-math training rows into a pinned mutation snapshot."""
        from glyphforge.sources.mutation import build_snapshot

        meta = build_snapshot(glyphfix_root, out)
        typer.echo(f"sha256 {meta['sha256']}")
        typer.echo(f"rows {meta['rows']}")

    @app.command()
    def doctor(pull: Annotated[bool, typer.Option("--pull", help="docker pull the pinned image first")] = False) -> None:
        """Check Docker, the pinned image, font packages, memory and the cache directory."""
        from glyphforge.render.doctor import run_checks

        results = run_checks(pull=pull)
        for c in results:
            typer.echo(f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        if not all(c.ok for c in results):
            raise typer.Exit(1)

    return app
