"""Tokenizer, label and normalizer parity with glyphfix-math on vendored golden vectors (no Docker needed)."""

import json
from pathlib import Path

from glyphforge.canon import canon_versions, canonical, canonicalize, equivalent, tokenize

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> tuple[dict, list[dict]]:
    """Return (_meta, rows) of a fixture; readers skip the _meta row."""
    first, *rows = [json.loads(x) for x in (FIX / name).read_text(encoding="utf-8").splitlines()]
    return first["_meta"], [r for r in rows if "_meta" not in r]


def test_meta_versions_match_glyphforge():
    for name in ("canon_parity.jsonl", "scorer_golden.jsonl", "render_golden.jsonl"):
        meta, _ = load(name)
        # filter_version intentionally diverges from glyphfix-math (filter 2) until the CR-01..03 fix lands upstream
        assert {k: meta[k] for k in canon_versions() if k != "filter_version"} == {k: v for k, v in canon_versions().items() if k != "filter_version"}, name
        assert meta["filter_version"] == "2", name


def test_canon_parity_rows():
    _, rows = load("canon_parity.jsonl")
    assert len(rows) == 2000
    bad = []
    for r in rows:
        got = (tokenize(r["raw_body"]), canonicalize(r["raw_body"], r["env"]), canonical(r["latex"]), canonical(r["raw_body"]))
        if got != (r["tokens"], r["label"], r["canonical"], r["canonical_raw"]) or r["label"] != r["latex"]:
            bad.append((r["arxiv_id"], r["raw_body"][:80]))
    assert not bad, f"{len(bad)} mismatches, first 5: {bad[:5]}"


def test_scorer_rows():
    _, rows = load("scorer_golden.jsonl")
    assert len(rows) == 117
    bad = [r["gt"] for r in rows
           if (canonical(r["gt"]), canonical(r["pred"]), equivalent(r["gt"], r["pred"])) != (r["canonical_gt"], r["canonical_pred"], r["equivalent"])]
    assert not bad, f"{len(bad)} mismatches, first 5: {bad[:5]}"
