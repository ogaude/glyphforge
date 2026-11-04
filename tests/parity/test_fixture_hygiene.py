"""Fixtures carry no local paths, personal email or image paths, and every committed formula is attributed."""

import json
import re
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"
JSONL = sorted(p for p in FIX.glob("*.jsonl") if p.name != "canon_golden.jsonl")


def test_no_sensitive_content():
    for p in FIX.iterdir():
        text = p.read_text(encoding="utf-8")
        assert not any(s in text for s in ("/home/", "/mnt/", "gmail")), p.name
        assert '"image"' not in text, p.name


def test_every_paper_is_attributed():
    attr = [json.loads(x) for x in (FIX / "ATTRIBUTION").read_text(encoding="utf-8").splitlines() if not x.startswith("#")]
    by_id = {a["arxiv_id"]: a for a in attr}
    assert all(a["authors"] and a["license_spdx"] in {"CC0-1.0", "CC-BY-4.0"} and a["version"] and a["license_uri"] for a in attr)
    for name in ("canon_parity.jsonl", "render_golden.jsonl"):
        for line in (FIX / name).read_text(encoding="utf-8").splitlines():
            if "arxiv_id" in (row := json.loads(line)):
                assert row["arxiv_id"] in by_id, (name, row["arxiv_id"])


def test_meta_header_present():
    assert {p.name for p in JSONL} == {"canon_parity.jsonl", "render_golden.jsonl", "scorer_golden.jsonl"}
    for p in JSONL:
        meta = json.loads(p.read_text(encoding="utf-8").splitlines()[0])["_meta"]
        assert re.fullmatch(r"[0-9a-f]{40}", meta["glyphfix_math_commit"]), p.name
