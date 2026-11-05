"""Self-contained HTML contact sheet for eye-checking grammar output and degradation strength."""

from __future__ import annotations

import base64
import json
import tempfile
from html import escape
from pathlib import Path
from typing import Literal

from glyphforge import pipeline
from glyphforge.degrade import apply_ops, degrade_ops
from glyphforge.export.card import pick_pairs
from glyphforge.recipe import DegradeSpec, Recipe, effective_styles, load_recipe
from glyphforge.store import read_store

CSS = "body{font-family:sans-serif}td,th{border:1px solid #bbb;padding:4px;vertical-align:top}img{max-width:420px;background:#fff}code{font-size:11px}"


def _img(png: bytes) -> str:
    return f'<img src="data:image/png;base64,{base64.b64encode(png).decode()}">'


def preview_html(store_dir: Path, *, degrade: DegradeSpec | None | Literal["store"] = "store", pairs: int = 48) -> str:
    """Contact sheet of up to ``pairs`` minimal pairs, round-robin over (class, font) cells, plus a degraded column when a spec is set."""
    root = Path(store_dir)
    run, samples, _ = read_store(root)
    if degrade == "store":
        degrade = DegradeSpec.model_validate(d) if (d := run["recipe"]["export"].get("degrade")) else None
    fonts = {s.font for s, _ in effective_styles(Recipe.model_validate(run["recipe"]))}
    picked, missing = pick_pairs(samples, fonts, pairs)
    n_pairs = len({s["pair_id"] for s in samples if s["control_kind"] == "pair"})

    def png(s: dict) -> bytes:
        return (root / s["image"]).read_bytes()

    def row(key: str, target: dict | None, hard: dict, tag: str) -> str:
        ops = degrade_ops(degrade, run["seed"], key) if degrade else []
        images = [_img(png(s)) if s else "" for s in (target, hard)]
        deg = [f"<td>{_img(apply_ops(png(s), ops)) if s else ''}</td>" for s in (target, hard)] + [f"<td><code>{escape(json.dumps(ops))}</code></td>"]
        labels = "<br>".join(escape(s["label"]) for s in (target, hard) if s)
        return (
            f"<tr><td>{images[0]}</td><td>{images[1]}</td>{''.join(deg) if degrade else ''}"
            f"<td>{escape(hard['error_class'])}{tag}</td><td>{escape(hard['font'])}</td><td><code>{labels}</code></td></tr>"
        )

    rows = [row(p["target"]["pair_id"], p["target"], p["hard_negative"], "") for p in picked]
    rows += [row(s["sample_id"], None, s, " (extra control)") for s in [s for s in samples if s["control_kind"] != "pair"][: max(0, pairs - len(picked))]]
    head = ["target", "hard negative", *(["degraded target", "degraded hard negative", "ops"] if degrade else []), "class", "font", "labels"]
    note = f"<p>not sampled: {escape(', '.join(f'{c}/{f}' for c, f in missing))}</p>" if missing else ""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>GlyphForge preview</title><style>{CSS}</style></head><body>"
        f"<h1>{len(picked)} pairs from {n_pairs}</h1>{note}<table><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr>{''.join(rows)}</table></body></html>"
    )


def preview_recipe(
    recipe: str | Path, *, pairs: int = 48, cache: Path | None = None, max_parallel: int | None = None, batch_size: int = 100
) -> str:
    """Render an oversampled run of ``recipe`` into a temporary store (no export) and return its contact sheet."""
    path = Path(recipe)
    base = load_recipe(path)
    derived = base.model_copy(
        update={
            "composition": base.composition.model_copy(update={"total": min(2 * pairs, pairs + 96)}),
            "export": base.export.model_copy(update={"formats": ()}),
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        pipeline.run(derived, Path(tmp) / "store", cache=cache, max_parallel=max_parallel, batch_size=batch_size, base_dir=path.resolve().parent)
        return preview_html(Path(tmp) / "store", degrade=derived.export.degrade, pairs=pairs)
