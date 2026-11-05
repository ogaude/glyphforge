# GlyphForge

GlyphForge generates rendered LaTeX formula images whose labels are provably correct: every label compiles, matches glyphfix-math's scoring conventions, and is dropped when an alternative label renders to the same pixels.

GlyphForge is an independent project. It is not affiliated with, endorsed by, or sponsored by LightOn.

## Install

```
pip install "glyphforge[cli,hf] @ git+https://github.com/ogaude/glyphforge@v0.1.0"
```

Library users who only need the import-light core can install it without extras:

```
pip install "glyphforge @ git+https://github.com/ogaude/glyphforge@v0.1.0"
```

PyPI packages (`pip install "glyphforge[cli,hf]"`) are planned if/when released; until then install from the git tag. The `[hf]` extra pins `datasets==5.1.0` exactly. GlyphForge supports Python 3.12 only and requires Pillow below 13.

## Requirements

Rendering needs Docker and the digest-pinned `texlive/texlive` image. Fetch and check it with `glyphforge doctor --pull`. Compilation runs with `--network none` and memory caps; generation is CPU-only.

## Quickstart

```
glyphforge validate recipes/grammar-small.yaml
glyphforge plan recipes/grammar-small.yaml
glyphforge run recipes/grammar-small.yaml out/
glyphforge preview out/ sheet.html
```

## Library

```python
from glyphforge import run

result = run("recipes/grammar-small.yaml", "out/")
print(result.rows_kept, result.rows_dropped)
```

## Dataset

The reference dataset is published at https://huggingface.co/datasets/ogaude/glyphforge-equations. It is synthetic and complements, but does not replace, the real equation crops in https://huggingface.co/datasets/ogaude/glyphfix-math-equations.

## Documentation

- [Recipes](docs/recipes.md)
- [Error classes](docs/error-classes.md)
- [Sources and licensing](docs/sources-and-licensing.md)
- [Export](docs/export.md)
- [Reproducibility](docs/reproducibility.md)
- [CLI](docs/cli.md)
- [Releasing](docs/releasing.md)

## License

Code is Apache-2.0. Dataset rows are CC0-1.0 (grammar) or CC BY (mutation), per row.

## Citation

See [CITATION.cff](CITATION.cff).
