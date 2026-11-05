# Export

`glyphforge run` auto-exports each format listed in the recipe's `export.formats`; `glyphforge export STORE OUT` exports an existing store later. See [CLI](cli.md).

## Formats

- `glyphfix`: the trainset layout consumed by glyphfix-math (`trainset.jsonl` plus root-relative PNGs).
- `parquet`: Hugging Face-ready Parquet shards with an embedded image column and Hugging Face schema metadata.

## The leak gate

The leak gate runs before every export and has no skip flag. Its policy:

> Exact canon formula, source formula or paper id match against the pinned blocklist fails the export; no exemptions

A hit prints a report (`leak <sample_id> <pair_id> <reason> <entry>`), exits 1 and writes nothing. The blocklist is pinned by path and sha256 in `export.blocklist`, the hash is always verified, and an empty blocklist is refused.

The blocklist is built by `glyphforge blocklist` from glyphfix-math data and holds the canonical formulas and base paper ids of: the v1 benchmark records and shards, the v1.1 fresh benchmark, the dev set, the page set, and the benchmark and quarantine id lists, plus the papers assigned to the held-out v1.1 splits. A row collides if its canonical label, its canonical source formula, or its base paper id is in the list.

## What an export writes

For a given store and export spec the output is byte-identical across runs.

```
OUT/<format>/
  data/train-00000-of-0000N.parquet   (parquet only)
  README.md                           dataset card (parquet only)
  ATTRIBUTION.md                      per-paper attribution
  export_manifest.json                counts, licences, roles, blocklist pin, leak policy, library versions
  assets/                             pair preview images (parquet only)
```

## Parquet columns

`arxiv_id`, `attempt`, `attribution`, `authors`, `bitmap_sha256`, `class_version`, `column_cm`, `control_glyph`, `control_kind`, `degrade_ops`, `env`, `error_class`, `family`, `flags`, `font`, `generator_version`, `height`, `image`, `image_digest`, `image_sha256`, `label`, `license`, `license_uri`, `n_sites`, `n_tokens`, `pad_px`, `pair_id`, `paper_id`, `paper_version`, `recipe_sha256`, `role`, `rules`, `sample_id`, `seed`, `site_level`, `size_pt`, `slot`, `source`, `source_canon`, `structure`, `style`, `style_preamble_sha256`, `width`, `wrapper`.

## Exporting with a different section

`glyphforge export STORE OUT --recipe other.yaml` takes only the export section of another recipe and records it in the manifest. Use it to re-export a store with a different format, shard size, or a degraded rebuild: add an `export.degrade` section to that recipe. Degradation is applied to the clean render after QC, so the ambiguity check always compares clean renders.

The published dataset uses clean renders only (no degradation).
