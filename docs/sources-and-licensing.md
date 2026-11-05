# Sources and licensing

## Where formulas come from

- **Grammar** (`source.kind: grammar`): formulas generated from a weighted grammar over the `math`, `astro-ph` and `physics` domains. They are synthetic and released under **CC0-1.0**.
- **Mutation** (`source.kind: mutation`): arXiv equations from a pinned snapshot, with glyph substitutions applied. These are **derivatives** of the original equations and stay under the licence of the paper version they came from.
- **Mix** (`source.kind: mix`): one grammar part and one mutation part with fixed shares.

Built-in, inline and file sources require an explicit `licence` in the recipe.

## Allowed licences

The allowed licences are exactly these keys:

| Licence | URI |
|---|---|
| `CC0-1.0` | https://creativecommons.org/publicdomain/zero/1.0/ |
| `CC-BY-3.0` | https://creativecommons.org/licenses/by/3.0/ |
| `CC-BY-4.0` | https://creativecommons.org/licenses/by/4.0/ |

A formula with any other licence is rejected when the source is loaded.

## Mutation snapshot

arXiv licences are per paper version, so the snapshot keeps `paper_version` next to `paper_id`. Each snapshot row has the keys `authors`, `env`, `latex`, `licence`, `paper_id`, `paper_version`, `split`. Only training-split rows pass the split and licence gate. A snapshot is built with `glyphforge snapshot` and pinned in the recipe by sha256 (see [recipes](recipes.md)).

## Per-row licence columns

Every exported row carries `license` (one of the keys above), `license_uri`, and `attribution`. For mutated rows `attribution` names the paper id, version, licence and authors and states that the sample was modified (synthetic glyph substitutions, re-rendered by GlyphForge). Grammar rows carry the CC0-1.0 dedication statement. The export also writes a per-paper `ATTRIBUTION.md` (see [export](export.md)).

Consumers must filter on `license` to honour their own constraints: for example keep only `CC0-1.0` rows for a fully public-domain subset, or keep CC BY rows and carry the attribution forward.

## Code licence

The GlyphForge code is licensed under **Apache-2.0**. This is separate from the data licences above: the dataset's licence is decided per row by `license`, never by the code licence.
