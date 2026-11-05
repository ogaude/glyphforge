"""Dataset card and ATTRIBUTION text, generated from run.json and the export manifest (stdlib only, no dates, no titles)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from html import escape
from importlib.resources import files
from itertools import zip_longest
from string import Template

from glyphforge.sources.base import LICENSES

NO_ENDORSE = "GlyphForge is an independent project. It is not affiliated with, endorsed by, or sponsored by LightOn."
PACKAGE_TITLE = "GlyphForge: a synthetic LaTeX formula generator with verified labels"
DATASET_TITLE = "glyphforge-equations: synthetic LaTeX formula images with glyph-level minimal pairs"
SIZE_CATEGORIES = ((1_000, "n<1K"), (10_000, "1K<n<10K"), (100_000, "10K<n<100K"), (1_000_000, "100K<n<1M"), (10_000_000, "1M<n<10M"))
CC0_STATEMENT = (
    "Rows under CC0-1.0 (synthetic grammar rows and rows derived from CC0-licensed papers) are dedicated to the public domain ("
    + LICENSES["CC0-1.0"]
    + ")."
)
CC_BY_STATEMENT = (
    "Rows under a CC BY licence are derivatives of arXiv equations; they keep the paper id (`arxiv_id`), version and authors, "
    "and the changes are noted in `attribution`. The per-paper list is in ATTRIBUTION.md."
)
MODIFIED = "modified: synthetic glyph substitutions, re-rendered by GlyphForge"


def _table(counts: dict, head: str) -> str:
    return "\n".join([f"| {head} | rows |", "| --- | --- |", *(f"| {k} | {v} |" for k, v in sorted(counts.items()))])


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(", ", ": "))


def pick_pairs(samples: list[dict], fonts: Iterable[str], n: int) -> tuple[list[dict[str, dict]], list[tuple[str, str]]]:
    """Up to ``n`` minimal pairs round-robin over (class, font) cells, plus the class/font cells with no pair."""
    by_pair: dict[str, dict[str, dict]] = {}
    for s in samples:
        if s["control_kind"] == "pair":
            by_pair.setdefault(s["pair_id"], {})[s["role"]] = s
    cells: dict[tuple[str, str], list[dict[str, dict]]] = {}
    for pid in sorted(by_pair, key=lambda p: by_pair[p]["target"]["sample_id"]):
        t = by_pair[pid]["target"]
        cells.setdefault((t["error_class"], t["font"]), []).append(by_pair[pid])
    keys = sorted(cells)
    picked = [p for rnd in zip_longest(*(cells[k] for k in keys)) for p in rnd if p is not None][:n]
    return picked, sorted({(c, f) for c in {k[0] for k in keys} for f in fonts} - set(keys))


def attribution_text(samples: Iterable[dict], *, derived: bool = True) -> str:
    papers: dict[tuple, dict] = {}
    cc0 = 0
    for s in samples:
        cc0 += not s["licence"].startswith("CC-BY")
        if s["paper_id"]:
            e = papers.setdefault((s["paper_id"], s["paper_version"] or ""), {"authors": s["authors"], "licence": s["licence"], "n": 0})
            e["n"] += 1
    lines = ["# Attribution", ""]
    for (pid, ver), e in sorted(papers.items()):
        ver = ver if not ver or ver.startswith("v") else "v" + ver
        tail = f"derived rows: {e['n']}; {MODIFIED}" if derived else f"formulas: {e['n']}"
        lines.append(f"- arXiv:{pid}{ver}; {', '.join(e['authors'])}; {e['licence']} ({LICENSES[e['licence']]}); {tail}")
    return "\n".join([*lines, "", f"{CC0_STATEMENT} Rows: {cc0}.", ""])


def licence_text(licenses: Iterable[str]) -> str:
    """The licence paragraph for exactly the licences present in the export."""
    present = set(licenses)
    return " ".join([*([CC0_STATEMENT] if "CC0-1.0" in present else []), *([CC_BY_STATEMENT] if any(k.startswith("CC-BY") for k in present) else [])])


def _cell(label: str) -> str:
    return f"<code>{escape(label).replace('|', '&#124;')}</code>"


def _grid(grid: list[dict]) -> str:
    rows = [
        f"| ![error]({g['target']})<br>{_cell(g['target_label'])} | ![control]({g['control']})<br>{_cell(g['control_label'])} | {g['error_class']} | {g['font']} |"
        for g in grid
    ]
    return "\n".join(["| error | control | class | font |", "| --- | --- | --- | --- |", *rows])


def _hub(repo_id: str | None) -> str:
    if repo_id is None:
        return ""
    return (
        f'## Usage\n\n```\nhf download {repo_id} --repo-type dataset\n```\n\n```python\nfrom datasets import load_dataset\n\n'
        f'ds = load_dataset("{repo_id}", split="train")\n```\n\n'
        f"```bibtex\n@misc{{glyphforge_equations,\n  author = {{ogaude}},\n  title = {{{DATASET_TITLE}}},\n  year = {{2026}},\n"
        f"  url = {{https://huggingface.co/datasets/{repo_id}}}\n}}\n```\n"
    )


def dataset_card(run: dict, manifest: dict, repo_id: str | None = None) -> str:
    degrade = manifest["degrade"]
    empty = manifest["empty_cells"]
    values = {
        "license_yaml": "\n".join(f"- {k.lower()}" for k in sorted(manifest["licenses"])), "n_rows": manifest["n_rows"],
        "pixel_policy_version": run["pixel_policy_version"], "roles_table": _table(manifest["roles"], "role"),
        "sources_table": _table(manifest["sources"], "source"), "licenses_table": _table(manifest["licenses"], "license"),
        "image_digest": manifest["image_digest"], "canon_versions": _json(run["canon_versions"]), "render_config": _json(run["render_config"]),
        "pyarrow_version": manifest["pyarrow_version"], "pillow_version": manifest["pillow_version"], "numpy_version": manifest["numpy_version"],
        "zlib_version": manifest["zlib_version"], "blocklist_path": manifest["blocklist"]["path"], "blocklist_sha256": manifest["blocklist"]["sha256"],
        "blocklist_formulas": manifest["blocklist"]["formulas"], "blocklist_papers": manifest["blocklist"]["papers"],
        "licence_text": licence_text(manifest["licenses"]),
        "leak_policy": manifest["leak_policy"],
        "degrade": "none" if degrade is None else f"`{_json(degrade)}` (sha256 `{manifest['degrade_sha256']}`)",
        "recipe_sha256": manifest["recipe_sha256"], "generator_version": manifest["generator_version"], "seed": run["seed"],
        "shards": ", ".join(f"`{n}`" for n in manifest["shards"]), "no_endorse": NO_ENDORSE, "package_title": PACKAGE_TITLE,
        "size_category": next(c for lim, c in SIZE_CATEGORIES if manifest["n_rows"] < lim),
        "classes_table": _table(manifest["error_classes"], "error class"), "fonts_table": _table(manifest["fonts"], "font"),
        "empty_cells": "Empty class/font cells: " + ", ".join(f"`{c}`" for c in empty) + "." if empty else "Every sampled class/font cell has at least one pair.",
        "sample_grid": _grid(manifest["grid"]), "hub_section": _hub(repo_id),
    }  # fmt: skip
    return Template(files("glyphforge.export").joinpath("card_template.md").read_text(encoding="utf-8")).substitute(values)
