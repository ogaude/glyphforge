"""Render a per-domain contact sheet of grammar formulas for eye-checking naturalness.

Writes OUT/<domain>.png (two columns of ink crops, formulas 0..N/2-1 left then N/2..N-1 right) and OUT/<domain>.md (index, class,
level, status, latex). Needs Docker and the pinned texlive image (one container at a time by default).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from glyphforge.errors import builtin_registry
from glyphforge.render import ink_crop, load_bitmap, render_many
from glyphforge.rng import slot_rng
from glyphforge.sources.grammar import DOMAINS, GrammarSource

CLASSES = ("greek.upsilon_v", "primes.prime_l", "digits.I_l", "decorations.drop_mathbf", "alphabets.drop_mathbb", "greek.nu_v")
LEVELS = ("base", "script", "scriptscript")
CELL_W, PAD = 760, 14


def _thumb(bitmap) -> Image.Image:
    crop = ink_crop(bitmap)
    img = Image.fromarray(crop if crop is not None else bitmap).convert("L")
    scale = min(0.5, CELL_W / img.width)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.Resampling.BICUBIC)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-domain", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-parallel", type=int, default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    registry = builtin_registry()
    for domain in DOMAINS:
        source, rows = GrammarSource({domain: 1}), []
        for i in range(args.per_domain):
            cls = registry.get(CLASSES[i % len(CLASSES)])
            level = LEVELS[(i // len(CLASSES)) % len(LEVELS)]
            formula = source.draw(cls, slot_rng(args.seed, f"sheet:{domain}", i), level=level, multiline=i % 5 == 4)
            if formula is not None:
                rows.append((i, cls.name, level, formula.latex))
        results = render_many([r[3] for r in rows], max_parallel=args.max_parallel)
        thumbs = [(_thumb(b) if (b := load_bitmap(res)) is not None else None) for res in results]
        half = -(-len(rows) // 2)
        cols = [thumbs[:half], thumbs[half:]]
        height = max(sum((t.height if t else 20) + PAD for t in col) for col in cols)
        sheet = Image.new("L", (2 * (CELL_W + PAD), height + PAD), 255)
        for c, col in enumerate(cols):
            y = PAD
            for t in col:
                if t:
                    sheet.paste(t, (c * (CELL_W + PAD) + PAD, y))
                y += (t.height if t else 20) + PAD
        sheet.save(args.out / f"{domain}.png")
        lines = [f"# {domain}: {len(rows)} formulas (row order in the PNG: left column then right column)", ""]
        lines += [f"{n}. `{cls}` {level} {res.status}: `{latex}`" for n, ((_, cls, level, latex), res) in enumerate(zip(rows, results, strict=True))]
        (args.out / f"{domain}.md").write_text("\n".join(lines) + "\n", "utf-8")
        print(domain, len(rows), sum(r.status == "rendered" for r in results), "rendered")


if __name__ == "__main__":
    main()
