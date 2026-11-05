import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from glyphforge import store
from glyphforge.recipe import load_recipe
from glyphforge.validate import check_store, field_errors, schema_text, validate_recipe

FIX = Path(__file__).parents[1] / "fixtures"
BL_SHA = hashlib.sha256((FIX / "blocklist.jsonl").read_bytes()).hexdigest()
MUT_SHA = hashlib.sha256((FIX / "mutation_snapshot.jsonl").read_bytes()).hexdigest()


def _write(tmp_path, **kw):
    recipe = {"source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["a+v"]}, "classes": ["greek.upsilon_v"], **kw}
    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _pinned(tmp_path, bl_sha=BL_SHA, mut_sha=MUT_SHA):
    shutil.copy(FIX / "blocklist.jsonl", tmp_path / "blocklist.jsonl")
    shutil.copy(FIX / "mutation_snapshot.jsonl", tmp_path / "snap.jsonl")
    return _write(
        tmp_path,
        source={"kind": "mutation", "path": "snap.jsonl", "sha256": mut_sha},
        export={"formats": ["glyphfix"], "blocklist": {"path": "blocklist.jsonl", "sha256": bl_sha}},
    )


def test_field_errors_use_dotted_paths(tmp_path):
    with pytest.raises(ValidationError) as ei:
        load_recipe(_write(tmp_path, composition={"total": 0}, export={"formats": ["glyphfix"]}))
    errs = field_errors(ei.value)
    assert "composition.total: Input should be greater than or equal to 1" in errs
    assert any(e.startswith("export: ") and "export.formats needs export.blocklist" in e for e in errs)


def test_schema_text_matches_published_file():
    published = Path(__file__).parents[2] / "src/glyphforge/recipe/schema.json"
    assert schema_text() == published.read_text(encoding="utf-8")


def test_valid_inline_recipe(tmp_path):
    out = validate_recipe(_write(tmp_path))
    assert out["ok"] is True and out["pins"] == [] and out["classes"] == ["greek.upsilon_v@1"] and len(out["recipe_sha256"]) == 64


def test_pins_verified(tmp_path):
    out = validate_recipe(_pinned(tmp_path))
    assert out["ok"] and {(p["kind"], p["ok"]) for p in out["pins"]} == {("mutation", True), ("blocklist", True)}


def test_wrong_sha_and_missing_file(tmp_path):
    out = validate_recipe(_pinned(tmp_path, bl_sha="0" * 64))
    assert not out["ok"] and any("sha256 mismatch" in p for p in out["problems"])
    assert [p["ok"] for p in out["pins"] if p["kind"] == "blocklist"] == [False]
    (tmp_path / "snap.jsonl").unlink()
    assert any("snap.jsonl: file not found" in p for p in validate_recipe(tmp_path / "r.yaml")["problems"])


def test_unknown_class_raises(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        validate_recipe(_write(tmp_path, classes=["nope.nope"]))


def _good_store(tmp_path):
    arr = np.full((8, 12), 255, np.uint8)
    png = store.png_bytes(arr)
    sha = hashlib.sha256(png).hexdigest()
    rows = []
    for role in ("target", "hard_negative"):
        row = dict.fromkeys(store.SAMPLE_KEYS)
        row.update(image=f"images/{sha[:2]}/{sha}.png", image_sha256=sha, pair_id="p0", role=role, control_kind="pair", slot=0, attempt=0,
                   sample_id=f"s0-{role}", label="x")  # fmt: skip
        rows.append(row)
    ledger = [{k: r.get(k) for k in store.LEDGER_KEYS} for r in rows]
    store.write_store(tmp_path / "store", rows, {sha: png}, ledger, {"schema_version": 3})
    return tmp_path / "store", sha


def test_check_store_good_and_damaged(tmp_path):
    root, sha = _good_store(tmp_path)
    assert check_store(root) == []
    lines = (root / "samples.jsonl").read_text().splitlines()
    (root / "samples.jsonl").write_text(lines[0] + "\n")
    assert check_store(root) == ["pair p0 incomplete"]
    (root / "images" / sha[:2] / f"{sha}.png").write_bytes(b"junk")
    assert f"image {sha} missing or corrupt" in check_store(root)
    run = json.loads((root / "run.json").read_text())
    (root / "run.json").write_text(json.dumps({**run, "schema_version": 2}))
    assert "store predates schema 3" in check_store(root)
    (root / "run.json").unlink()
    assert "run.json missing" in check_store(root)
    (root / "samples.jsonl").write_text("{not json\n")
    assert any(p.startswith("samples.jsonl unreadable") for p in check_store(root))
