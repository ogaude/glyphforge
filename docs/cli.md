# CLI

Install the CLI extra (`glyphforge[cli]`) to get the `glyphforge` command. Every command is a thin shell over a library function.

Exit codes: `0` success; `1` a leak-gate hit, a pinned-file sha256 mismatch, a failed check, or a render infrastructure or OS error; `2` usage or validation errors (schema errors by field path, existing output, missing files).

Operational options shared by the rendering commands never change the output: `--max-workers N` (parallel Docker renders), `--docker-memory GB` (cap per render), `--cache DIR` (render cache), `--batch-size N` (formulas per Docker batch, default 100).

Environment overrides: `GLYPHFORGE_CACHE` (render cache directory), `GLYPHFORGE_DOCKER_MEMORY_GB` (default 4), `GLYPHFORGE_MAX_WORKERS` (default 3). A new render starts only while at least 1.5 GB of memory stays available.

## run

`glyphforge run RECIPE OUT [--no-export] [--max-workers N] [--docker-memory GB] [--cache DIR] [--batch-size N]`

Runs the recipe into `OUT`, then exports `OUT/export/<format>` for each format the recipe lists. It resumes a matching journal in `OUT` and refuses (exit 2) an `OUT` that holds `run.json` or a journal of another recipe. `--no-export` stops after the store. A blocklist hit exits 1 and leaves the store complete. Prints `recipe_sha256`, kept and dropped rows and any shortfall.

## plan

`glyphforge plan RECIPE [--json] [--max-workers N] [--docker-memory GB]`

Dry run: quota table, totals, recipe hash and a rough wall-time and memory estimate. No Docker, nothing written.

## validate

`glyphforge validate RECIPE [--store DIR] [--schema FILE] [--json]`

Checks the recipe without Docker: schema errors by field path (exit 2), class resolution, pinned-file sha256 (mismatch exits 1). `--store` also checks a store's integrity; `--schema` writes the recipe JSON Schema to `FILE`.

## export

`glyphforge export STORE OUT [--recipe FILE] [--format glyphfix|parquet] [--json]`

Exports a store to `OUT/<format>` with the leak gate always run first. By default it uses the store's frozen export section; `--recipe` takes only the export section of another file (recorded in the manifest), and its blocklist path resolves against that file's directory. The blocklist sha256 is always verified and an empty blocklist is refused. A leak hit prints the hit report and exits 1 with nothing written.

## preview

`glyphforge preview SOURCE OUT [--pairs N] [--max-workers N] [--docker-memory GB] [--cache DIR] [--batch-size N]`

Writes a self-contained HTML contact sheet (default 48 pairs) from a store directory (no rendering) or a recipe file (renders a small run). Refuses to overwrite `OUT`.

## blocklist

`glyphforge blocklist GLYPHFIX_ROOT OUT`

Builds the pinned leak blocklist from the evaluation and test data of a glyphfix-math checkout and prints its sha256 and per-set counts. Refuses to overwrite.

## snapshot

`glyphforge snapshot GLYPHFIX_ROOT OUT`

Freezes the training rows of a glyphfix-math checkout into a pinned mutation snapshot and prints its sha256 and row count.

## doctor

`glyphforge doctor [--pull]`

Checks Docker, the pinned image, font packages, memory and the cache directory. `--pull` runs `docker pull` for the pinned image first. Exits 1 if any check fails.
