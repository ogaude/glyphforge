# Reproducibility

The published dataset can be rebuilt from public artifacts: the committed recipe, the `source/` files published next to the dataset, and the pinned renderer image.

## Procedure

1. Clone `github.com/ogaude/glyphforge` at the release tag and run `uv sync`.
2. Fetch the pinned renderer image and check the machine: `glyphforge doctor --pull`. The image is pinned by digest `sha256:0f4884ca7d287f47ab466d2dd405d4c901c576585363f628863a7ca7eea21301`; the digest is part of every cache key and recorded on every sample.
3. Fill `recipes/source/` (not committed) with the published mutation snapshot and blocklist:

   ```
   hf download ogaude/glyphforge-equations --repo-type dataset --include "source/*" --local-dir recipes
   ```

4. Validate: `glyphforge validate recipes/glyphforge-equations-v1.yaml`. Each pinned file is checked against the sha256 in the recipe; a mismatch is refused (exit 1).
5. Run: `glyphforge run recipes/glyphforge-equations-v1.yaml out/`.
6. Compare `recipe_sha256` and the shard sha256 values in `out/export/parquet/export_manifest.json` with the dataset card.

## Why it reproduces

- Per-sample seeds are derived by hashing `seed:stage:slot:attempt`, and sampling uses only `random.Random.random()`, which is stable across Python versions. Any sample can be regenerated alone and the worker count never changes the result.
- numpy is used only for degradation noise (off in the published recipe), and its version is recorded in the export manifest.
- PNG encoding uses fixed settings and no metadata, so identical pixels give identical bytes.
- The renderer image, preamble hash and filter versions are part of the render cache key.

## Cost

Rebuilding needs Docker and many CPU hours. Renders run with `--network none` and a memory cap, and a new container starts only while at least 1.5 GB of memory stays available; lower `--max-workers` or `--docker-memory` on a small machine. `glyphforge plan` prints an estimate before you commit to a run.

## Scheduled CI

The nightly scheduled workflows are paused by GitHub after a long period of repository inactivity. They can be started by hand with `workflow_dispatch`.
