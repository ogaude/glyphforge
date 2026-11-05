# Error classes

An error class describes one glyph-level confusion. For each site where it applies, GlyphForge builds a minimal pair: the target formula (the label) and a hard negative that differs at that site by the confusable. Each pair carries a shared `pair_id`; the two rows have `role` `target` and `hard_negative`. Extra control rows (`control_kind` `extra`) have no pair partner. The recipe's `composition.hard_negative_ratio` sets how many controls accompany each error row.

Ambiguity is measured by QC, never decided by a class: if the alternative label renders to identical pixels the sample is dropped (`qc.ambiguity: drop`) or kept and flagged (`flag`).

## Built-in classes

| name | family | version |
|---|---|---|
| `alphabets.drop_mathbb` | alphabets | 1 |
| `alphabets.drop_mathcal` | alphabets | 1 |
| `alphabets.drop_mathfrak` | alphabets | 1 |
| `alphabets.drop_mathrm` | alphabets | 1 |
| `alphabets.drop_mathscr` | alphabets | 1 |
| `alphabets.drop_mathsf` | alphabets | 1 |
| `alphabets.mathbb_mathbf` | alphabets | 1 |
| `alphabets.mathcal_mathscr` | alphabets | 1 |
| `alphabets.mathfrak_mathcal` | alphabets | 1 |
| `alphabets.mathrm_mathsf` | alphabets | 1 |
| `decorations.bar_overline` | decorations | 1 |
| `decorations.boldsymbol_bm` | decorations | 1 |
| `decorations.drop_bar` | decorations | 1 |
| `decorations.drop_bm` | decorations | 1 |
| `decorations.drop_boldsymbol` | decorations | 1 |
| `decorations.drop_dot` | decorations | 1 |
| `decorations.drop_hat` | decorations | 1 |
| `decorations.drop_mathbf` | decorations | 1 |
| `decorations.drop_overline` | decorations | 1 |
| `decorations.drop_tilde` | decorations | 1 |
| `decorations.drop_underline` | decorations | 1 |
| `decorations.drop_vec` | decorations | 1 |
| `decorations.hat_widehat` | decorations | 1 |
| `decorations.mathbf_bm` | decorations | 1 |
| `decorations.mathbf_boldsymbol` | decorations | 1 |
| `decorations.tilde_widetilde` | decorations | 1 |
| `decorations.vec_overrightarrow` | decorations | 1 |
| `digits.I_bar` | digits | 1 |
| `digits.I_l` | digits | 1 |
| `digits.I_one` | digits | 1 |
| `digits.O_zero` | digits | 1 |
| `digits.ell_l` | digits | 1 |
| `digits.l_bar` | digits | 1 |
| `digits.l_one` | digits | 1 |
| `digits.one_bar` | digits | 1 |
| `greek.chi_x` | greek | 1 |
| `greek.iota_i` | greek | 1 |
| `greek.kappa_k` | greek | 1 |
| `greek.nu_v` | greek | 1 |
| `greek.omicron_o` | greek | 1 |
| `greek.rho_p` | greek | 1 |
| `greek.upsilon_v` | greek | 1 |
| `primes.dquote` | primes | 1 |
| `primes.dropped` | primes | 1 |
| `primes.prime_l` | primes | 1 |

Select a subset with the recipe `classes` key; set per-class shares with `composition.shares`.

## Plugin API

A class is any object implementing the `ErrorClass` protocol from `glyphforge.errors`:

- attributes `name`, `version`, `family`, `packages` (a frozenset of LaTeX package names; no `\usepackage` in output);
- `sites(latex) -> tuple[Site, ...]`: candidate locations (character offsets, `end` exclusive);
- `apply(latex, site, rng) -> Variant`: the target, the hard negative and the control glyph. It must be pure, deterministic and free of I/O.

Two declarative helpers cover the common cases: `ConfusionPair` (single-token swap) and `CommandPair` (command swap or dropped command). `check_error_class` validates a class. Names match `^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$` and must be unique.

Register a class in three ways:

```python
from glyphforge.errors import ConfusionPair, register

register(ConfusionPair(name="mine.prime", truth="'", confusable="l", family="mine"))
```

- `register(obj)` (library): adds to the default registry.
- Recipe `plugins: [my_pkg.classes]`: the module is imported and its `register_classes(registry)` function is called.
- Recipe `entry_points: true`: classes are loaded from the `glyphforge.error_classes` entry-point group; an entry point is either a class instance or a callable taking the registry.

A class's `name@version` is recorded on every sample; bump `version` when its behaviour changes.
