---
license:
$license_yaml
task_categories:
- image-to-text
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*.parquet
---

# GlyphForge synthetic formula images

GlyphForge is an independent project; it is not made or endorsed by LightOn.

## Summary

$n_rows rendered LaTeX formula images, each with a label that compiles and canonicalises to the stored text. Images are raw ink crops
plus the recorded padding; they are never resized (the consumer applies its own pixel policy, version $pixel_policy_version).

## Composition

Rows by role:

$roles_table

Rows by source:

$sources_table

## Licensing

Every row carries its own `license`, `license_uri` and a ready-to-cite `attribution` string.

$licenses_table

$licence_text

## Rendering

- Renderer image digest: `$image_digest`
- Canonicalisation and render rule versions: `$canon_versions`
- Render configuration: `$render_config`
- Library versions: pyarrow $pyarrow_version, Pillow $pillow_version, numpy $numpy_version, zlib $zlib_version

## Leakage policy

Blocklist pin: `$blocklist_path` (sha256 `$blocklist_sha256`), $blocklist_formulas formulas and $blocklist_papers papers.

$leak_policy

## Degradation

$degrade

## Provenance

- recipe_sha256: `$recipe_sha256`
- generator_version: `$generator_version`
- seed: `$seed`
- Files: $shards
