---
pretty_name: GlyphForge synthetic formula images
license:
$license_yaml
task_categories:
- image-to-text
tags:
- ocr
- latex
- math
- formula-recognition
- synthetic
size_categories:
- $size_category
annotations_creators:
- machine-generated
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*.parquet
---

# GlyphForge synthetic formula images

$no_endorse

## Summary

$n_rows rendered LaTeX formula images, each with a label that compiles and canonicalises to the stored text. Images are raw ink crops
plus the recorded padding; they are never resized (the consumer applies its own pixel policy, version $pixel_policy_version).
The data is synthetic: it complements and does not replace real equation crops such as
https://huggingface.co/datasets/ogaude/glyphfix-math-equations.

## Intended use

Training OCR models on glyph-level confusions (primes vs `l`, Greek/Latin look-alikes, digit/letter confusions, decorations) and a
secondary stress test. Out of scope: replacing a benchmark, or evidence of accuracy on real papers.

## Composition

Rows by role:

$roles_table

Rows by source:

$sources_table

Rows by error class:

$classes_table

Rows by font:

$fonts_table

## Samples

$sample_grid

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

## Limitations

- The synthetic distribution differs from real papers.
- Fonts are limited to the sampled packages.
- Class/font cells can have zero yield. $empty_cells
- Labels follow one output style.
- The ambiguity filter compares clean renders at 300 DPI only.

## Reproducing

The recipe pins the snapshot and blocklist sha256, and `glyphforge validate` refuses a mismatch. `glyphforge run <recipe> <out>`
rebuilds the dataset. For a hub dataset, `source/` holds the snapshot and blocklist.

## Provenance

- recipe_sha256: `$recipe_sha256`
- generator_version: `$generator_version`
- seed: `$seed`
- Files: $shards

$hub_section
## Citation

```bibtex
@misc{glyphforge,
  author = {ogaude},
  title = {$package_title},
  year = {2026},
  version = {$generator_version},
  url = {https://github.com/ogaude/glyphforge}
}
```
