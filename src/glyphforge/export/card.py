"""Dataset card and ATTRIBUTION text, generated from run.json and the export manifest (stdlib only, no dates, no titles)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib.resources import files
from string import Template

from glyphforge.sources.base import LICENSES

CC0_STATEMENT = "Grammar rows are synthetic and dedicated to the public domain under CC0-1.0 (" + LICENSES["CC0-1.0"] + ")."
MODIFIED = "modified: synthetic glyph substitutions, re-rendered by GlyphForge"


def _table(counts: dict, head: str) -> str:
    return "\n".join([f"| {head} | rows |", "| --- | --- |", *(f"| {k} | {v} |" for k, v in sorted(counts.items()))])


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(", ", ": "))


def attribution_text(samples: Iterable[dict]) -> str:
    papers: dict[tuple, dict] = {}
    cc0 = 0
    for s in samples:
        if not s["licence"].startswith("CC-BY"):
            cc0 += 1
            continue
        e = papers.setdefault((s["paper_id"], s["paper_version"] or ""), {"authors": s["authors"], "licence": s["licence"], "n": 0})
        e["n"] += 1
    lines = ["# Attribution", ""]
    for (pid, ver), e in sorted(papers.items()):
        ver = ver if not ver or ver.startswith("v") else "v" + ver
        lines += [
            f"- arXiv:{pid}{ver}; {', '.join(e['authors'])}; {e['licence']} ({LICENSES[e['licence']]}); derived rows: {e['n']}; {MODIFIED}"
        ]
    return "\n".join([*lines, "", f"{CC0_STATEMENT} Rows: {cc0}.", ""])


def dataset_card(run: dict, manifest: dict) -> str:
    degrade = manifest["degrade"]
    values = {
        "license_yaml": "\n".join(f"- {k.lower()}" for k in sorted(manifest["licenses"])), "n_rows": manifest["n_rows"],
        "pixel_policy_version": run["pixel_policy_version"], "roles_table": _table(manifest["roles"], "role"),
        "sources_table": _table(manifest["sources"], "source"), "licenses_table": _table(manifest["licenses"], "license"),
        "image_digest": manifest["image_digest"], "canon_versions": _json(run["canon_versions"]), "render_config": _json(run["render_config"]),
        "pyarrow_version": manifest["pyarrow_version"], "pillow_version": manifest["pillow_version"], "numpy_version": manifest["numpy_version"],
        "zlib_version": manifest["zlib_version"], "blocklist_path": manifest["blocklist"]["path"], "blocklist_sha256": manifest["blocklist"]["sha256"],
        "leak_policy": manifest["leak_policy"],
        "degrade": "none" if degrade is None else f"`{_json(degrade)}` (sha256 `{manifest['degrade_sha256']}`)",
        "recipe_sha256": manifest["recipe_sha256"], "generator_version": manifest["generator_version"], "seed": run["seed"],
        "shards": ", ".join(f"`{n}`" for n in manifest["shards"]),
    }  # fmt: skip
    return Template(files("glyphforge.export").joinpath("card_template.md").read_text(encoding="utf-8")).substitute(values)
