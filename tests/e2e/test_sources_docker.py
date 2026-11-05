"""End-to-end through the digest-pinned sandbox: source mix, structures, typography, reports, resume and the snapshot pin."""

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from glyphforge import pipeline
from glyphforge.canon.safety import check_render
from glyphforge.pipeline import build_registry, run
from glyphforge.recipe import Recipe, StyleSpec, to_style
from glyphforge.render import docker, render_many
from glyphforge.resources import mem_available_bytes
from glyphforge.store import read_store

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mutation_snapshot.jsonl"
CLASSES = ["greek.upsilon_v", "primes.prime_l", "digits.I_l", "decorations.drop_mathbf"]
PAD = 2
assert mem_available_bytes() >= int(1.5 * 2**30), "docker e2e needs MemAvailable >= 1.5 GB"


def _snapshot(base: Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, base / "snap.jsonl")
    return {"kind": "mutation", "path": "snap.jsonl", "sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest()}


def _mix(base: Path) -> dict:
    return {
        "seed": 21,
        "source": {"kind": "mix", "parts": [{"kind": "grammar", "domains": {"math": 1, "physics": 1}}, _snapshot(base)]},
        "classes": CLASSES,
        "composition": {"total": 20, "hard_negative_ratio": 1.5},
        "typography": {"fonts": {"cm": 2, "libertine": 1, "newtx": 1}, "sizes": {9: 1, 10: 1, 12: 1}},
        "structure": {"kinds": {"display": 0.5, "numbered": 0.25, "inline": 0.25}},
        "render": {"pad_px": PAD},
    }


@pytest.fixture(scope="module")
def mix(tmp_path_factory):
    base = tmp_path_factory.mktemp("mix")
    result = run(_mix(base), base / "out", cache=base / "cache", max_parallel=2, base_dir=base)
    return (base, result, *read_store(base / "out"))


def test_mix_quotas_and_sources(mix):
    _, result, run_json, samples, _ = mix
    sf = result.shortfall
    for name in sf["short_classes"]:
        assert set(sf["classes"][name]) == {"target", "achieved", "short"} and sf["classes"][name]["short"] > 0
    grammar = [s for s in samples if s["source"] == "grammar"]
    mutation = [s for s in samples if s["source"] == "mutation"]
    assert grammar and mutation
    assert {s["licence"] for s in grammar} == {"CC0-1.0"} and all(s["paper_id"] for s in grammar)
    assert max(Counter(s["paper_id"] for s in grammar).values()) <= 30
    assert all(s["paper_id"].startswith("fixture:") for s in mutation)
    assert {s["error_class"] for s in samples} <= set(CLASSES) and len({s["font"] for s in samples}) > 1
    print(f"mix: kept {result.rows_kept} dropped {result.rows_dropped} shortfall {sf['short_total']} {sf['short_classes']}")
    print("by_reason:", run_json["counts"]["by_reason"], "scale warnings:", run_json["scale"]["warnings"], "balance warnings:", result.warnings)


def test_structures_tag_inline_and_sizes(mix):
    base, _, run_json, samples, _ = mix
    assert {s["structure"] for s in samples} >= {"display", "numbered", "inline"}
    registry = build_registry(Recipe())
    numbered = [s for s in samples if s["structure"] == "numbered"]
    assert numbered
    for s in numbered[:6]:
        body, tag = s["label"].split("\n\\tag{")
        assert tag.endswith("}") and tag[:-1].isdigit()
        spec = run_json["styles"][s["style"]]
        style = to_style(StyleSpec(name=s["style"], font=spec["font"], size=spec["size"], packages=tuple(spec["packages"])), registry.get(s["error_class"]).packages, s["column_cm"])
        assert style.preamble_sha256 == s["style_preamble_sha256"]
        (untagged,) = render_many([body], wrapper="line", style=style, cache=base / "cache", max_parallel=2)
        assert untagged.status == "rendered" and untagged.bitmap_sha256 != s["bitmap_sha256"], "tag must be visible"
    for s in (s for s in samples if s["structure"] == "inline"):
        assert "$" in s["label"] and check_render(s["label"], "line") is None
    assert all(s["n_tokens"] <= 440 for s in samples)
    assert all(s["width"] >= 2 * PAD + 1 and s["height"] >= 2 * PAD + 1 for s in samples)


def test_extra_controls_share_the_slot_look(mix):
    _, _, _, samples, _ = mix
    by_slot: dict[int, list[dict]] = {}
    for s in samples:
        by_slot.setdefault(s["slot"], []).append(s)
    extras = [r for rows in by_slot.values() for r in rows if r["control_kind"] == "extra"]
    assert extras
    for r in extras:
        (target,) = (t for t in by_slot[r["slot"]] if t["role"] == "target")
        assert all(r[k] == target[k] for k in ("style", "font", "size_pt", "column_cm", "structure"))


def test_reports_present(mix):
    _, _, run_json, _, _ = mix
    assert any("scale gap" in w for w in run_json["scale"]["warnings"])
    assert "balance" in run_json and "warnings" in run_json["balance"]
    assert run_json["mix_shares"] == [0.3, 0.7] and [s["kind"] for s in run_json["sources"]] == ["grammar", "mutation"]


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_resume_is_byte_identical(tmp_path, monkeypatch):
    recipe = {
        "seed": 8,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["a+v", r"\upsilon+b", r"v_{a}+c", r"v+\fail", r"d+v+\fail"]},
        "classes": ["greek.upsilon_v"],
        "styles": [{"name": "default", "font": "cm", "size": 12}],
        "composition": {"total": 6},
    }
    run(recipe, tmp_path / "a", cache=tmp_path / "ca", max_parallel=1)
    real, calls = pipeline.render_many, []

    def killer(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("killed")
        return real(*a, **kw)

    monkeypatch.setattr(pipeline, "render_many", killer)
    with pytest.raises(RuntimeError, match="killed"):
        run(recipe, tmp_path / "b", cache=tmp_path / "cb", max_parallel=1)
    assert (tmp_path / "b" / ".journal").is_dir() and not (tmp_path / "b" / "run.json").exists()
    monkeypatch.setattr(pipeline, "render_many", real)
    run(recipe, tmp_path / "b", cache=tmp_path / "cb", max_parallel=1)
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")
    assert not (tmp_path / "b" / ".journal").exists()


def test_snapshot_pin_rejects_edited_file(tmp_path, monkeypatch):
    recipe = _mix(tmp_path)
    with (tmp_path / "snap.jsonl").open("ab") as fh:
        fh.write(b"\n")
    monkeypatch.setattr(pipeline, "render_many", lambda *a, **k: pytest.fail("rendered before the pin check"))
    with pytest.raises(ValueError, match="sha256 mismatch"):
        run(recipe, tmp_path / "out", cache=tmp_path / "cache", max_parallel=2, base_dir=tmp_path)
    assert json.loads(FIXTURE.read_text().splitlines()[0])["licence"] == "CC0-1.0"
