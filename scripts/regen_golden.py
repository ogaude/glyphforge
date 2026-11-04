"""Regenerate the golden fixtures under tests/fixtures from glyphfix-math.

Run it ONLY with the sibling checkout's own interpreter, never in CI and never in GlyphForge's environment:

    <glyphfix-math>/.venv/bin/python scripts/regen_golden.py --sibling <glyphfix-math> --scratch <empty render cache dir>

This is the only GlyphForge file allowed to import glyphfix_math; it is not part of the package. Output is deterministic
(seeded sampling, sorted keys, no timestamps), so two runs produce byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

PRIME = re.compile(r"'|\\prime")
DECORATION = re.compile(r"\\(?:mathbf|boldsymbol|bm|bar|overline|underline|hat|tilde|vec|dot)(?![A-Za-z])")
ALPHABET = re.compile(r"\\(?:mathbb|mathcal|mathscr|mathfrak|mathrm|mathsf)(?![A-Za-z])")
LICENSES = {"CC0-1.0", "CC-BY-4.0"}
HANDWRITTEN = [r"\undefinedcmd{x}", r"\frac{a}{b", "x+" * 400 + "x", r"\phantom{x}", r"\input{/etc/passwd}", r"\immediate\write18{ls}",
               r"\def\a{b}\a", "", "f'", r"f^{\prime}", r"\bm{x}", r"\boldsymbol{x}", "x+1", "$$x+1$$"]
EXPECTED_STATUS = {"compile-failed", "overflow", "blank-page", "rejected", "empty"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sibling", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--docker-memory-gb", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20261104)
    a = ap.parse_args()
    gm, out, scratch = a.sibling.resolve(), a.out, a.scratch.resolve()
    if (Path.home() / ".cache" / "glyphfix_math").resolve() in (scratch, *scratch.parents):
        sys.exit("refusing to use a scratch dir inside ~/.cache/glyphfix_math")
    sys.path.insert(0, str(gm / "src"))
    from glyphfix_math import guard, render
    from glyphfix_math.corpus.canon import CANON_RULES_VERSION, canonicalize
    from glyphfix_math.latex_tokens import tokenize
    from glyphfix_math.normalize import NORMALIZE_RULES_VERSION, canonical, equivalent

    guard.DOCKER_MEMORY, guard.DOCKER_MEMORY_GB = f"{a.docker_memory_gb}g", a.docker_memory_gb
    rng = random.Random(a.seed)
    meta = {"_meta": {
        "glyphfix_math_commit": subprocess.run(["git", "-C", str(gm), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(),
        "canon_rules_version": CANON_RULES_VERSION, "normalize_rules_version": NORMALIZE_RULES_VERSION, "wrap_version": render.WRAP_VERSION,
        "filter_version": render.FILTER_VERSION, "image_digest": render.IMAGE_DIGEST, "preamble_sha256": render.PREAMBLE_SHA256,
        "render_dpi": render.RENDER_DPI, "seed": a.seed, "generator": "scripts/regen_golden.py"}}

    def jl(path: Path) -> list[dict]:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def write(name: str, rows: list[dict]) -> None:
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in [meta, *rows])
        (out / name).write_bytes(text.encode("utf-8"))

    catalog = {c["arxiv_id"]: c for c in jl(gm / "data/catalog/train_dev.jsonl")
               if c["split"] == "train" and not c["quarantined"] and c["authors"]}
    records = sorted((r for r in jl(gm / "data/corpus/train/records.jsonl")
                      if r["split"] == "train" and r["license_spdx"] in LICENSES and r["arxiv_id"] in catalog),
                     key=lambda r: (r["arxiv_id"], r["id"]))
    out.mkdir(parents=True, exist_ok=True)

    # canon parity: all gather rows, then align and equation in corpus proportion up to 2000
    by_env = {e: [r for r in records if r["env"] == e] for e in ("gather", "align", "equation")}
    n_rest = 2000 - len(by_env["gather"])
    n_align = round(n_rest * len(by_env["align"]) / (len(by_env["align"]) + len(by_env["equation"])))
    chosen = by_env["gather"] + rng.sample(by_env["align"], n_align) + rng.sample(by_env["equation"], n_rest - n_align)
    chosen.sort(key=lambda r: (r["arxiv_id"], r["id"]))
    canon_rows = []
    for r in chosen:
        label = canonicalize(r["raw_body"], r["env"])
        assert label == r["latex"], f"label drift for {r['id']}"
        canon_rows.append({"arxiv_id": r["arxiv_id"], "paper_version": r["paper_version"], "env": r["env"], "raw_body": r["raw_body"], "latex": r["latex"],
                           "tokens": tokenize(r["raw_body"]), "label": label, "canonical": canonical(r["latex"]), "canonical_raw": canonical(r["raw_body"])})
    write("canon_parity.jsonl", canon_rows)

    # scorer goldens: glyphfix-math's own pairs, outputs computed by glyphfix-math
    pairs = [{"source": "scorer_golden", "gt": x["gt"], "pred": x["pred"]} for x in jl(gm / "tests/fixtures/scorer_golden.jsonl")]
    pairs += [{"source": "adversarial", "gt": x["gt_latex"], "pred": x["pred_latex"], "id": x["id"], "expect": x["expect"], "expect_class": x.get("expect_class")}
              for x in jl(gm / "tests/fixtures/adversarial_predictions.jsonl")]
    for p in pairs:
        p.update(canonical_gt=canonical(p["gt"]), canonical_pred=canonical(p["pred"]), equivalent=equivalent(p["gt"], p["pred"]))
    write("scorer_golden.jsonl", pairs)

    # render goldens: strata over eligible records (no duplicate latex across strata) plus handwritten edge cases
    pool = [r for r in records if r["latex"].strip()]
    strata = [("aligned", 40, lambda r: r["env"] in ("align", "gather") and render._needs_aligned(r["latex"])),
              ("prime", 30, lambda r: PRIME.search(r["latex"])), ("decoration", 30, lambda r: DECORATION.search(r["latex"])),
              ("alphabet", 30, lambda r: ALPHABET.search(r["latex"])), ("equation", 50, lambda r: r["env"] == "equation")]
    picked, seen = [], set()
    for _, n, pred in strata:
        cand = [r for r in pool if pred(r) and r["latex"] not in seen]
        for r in rng.sample(cand, n):
            seen.add(r["latex"])
            picked.append(r)
    # record height/width include the 10 px pad on each side that the corpus builder adds around the ink crop
    items = [(r["latex"], "train", r) for r in picked] + [(x, "handwritten", None) for x in HANDWRITTEN]
    results = render.render_many([x[0] for x in items], batch_size=100, cache=scratch)
    rows = []
    for (latex, source, r), res in zip(items, results, strict=True):
        row = {"latex": latex, "source": source, "cache_key": render.cache_key(latex), "status": res.status,
               "shape": list(res.shape) if res.shape else None, "bitmap_sha256": res.bitmap_sha256, "note": res.note}
        if r:
            assert res.status == "rendered" and res.bitmap_sha256 == r["bitmap_sha256"] and row["shape"] == [r["height"] - 20, r["width"] - 20], f"render drift for {r['id']}"
            row.update(arxiv_id=r["arxiv_id"], paper_version=r["paper_version"])
        rows.append(row)
    assert EXPECTED_STATUS <= {x["status"] for x in rows}, "missing expected handwritten statuses"
    rows.sort(key=lambda x: (x["source"], x.get("arxiv_id", ""), x["latex"]))
    write("render_golden.jsonl", rows)

    # attribution for every paper whose formula is committed
    ids = sorted({x["arxiv_id"] for x in (*canon_rows, *rows) if "arxiv_id" in x})
    head = ["# Attribution for the formula excerpts in tests/fixtures/canon_parity.jsonl and render_golden.jsonl.",
            "# Formulas are excerpts from arXiv papers licensed CC BY 4.0 or CC0 1.0; one JSON object per paper below.",
            f"# Generated by scripts/regen_golden.py from glyphfix-math commit {meta['_meta']['glyphfix_math_commit']}.",
            "# canon_golden.jsonl and the scorer pairs are hand-written test cases from glyphfix-math, not paper excerpts."]
    body = [json.dumps({"arxiv_id": i, "version": catalog[i]["version"], "license_spdx": catalog[i]["license_spdx"],
                        "license_uri": catalog[i]["license_uri"], "authors": catalog[i]["authors"]}, ensure_ascii=False, sort_keys=True) for i in ids]
    (out / "ATTRIBUTION").write_bytes(("\n".join(head + body) + "\n").encode("utf-8"))
    print(f"canon={len(canon_rows)} scorer={len(pairs)} render={len(rows)} papers={len(ids)}")


if __name__ == "__main__":
    main()
