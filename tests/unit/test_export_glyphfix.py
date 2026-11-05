import json

import pytest
from PIL import Image

from glyphforge.export import control_glyphs_used, export_glyphfix
from glyphforge.export.glyphfix import ROLE_GROUP

REQUIRED_KEYS = ("id", "paper_id", "image", "latex", "target_text", "group", "width", "height")
FENCE = "`" * 3


@pytest.fixture
def exported(tmp_path, make_store):
    s = make_store()
    manifest = export_glyphfix(s.store, tmp_path / "out", spec=s.spec, base_dir=s.base_dir)
    return tmp_path / "out", manifest, s.samples


def _rows(out):
    return [json.loads(line) for line in (out / "trainset.jsonl").read_text().splitlines()]


def test_vendored_contract(exported):
    out, _, _ = exported
    rows = _rows(out)
    assert len(rows) == 5
    for r in rows:
        assert all(k in r for k in REQUIRED_KEYS)
        assert r["target_text"] == FENCE + "latex\n" + r["latex"] + "\n" + FENCE
        assert r["group"] == ROLE_GROUP["target" if r["group"] == "error" else "hard_negative"]
        with Image.open(out / r["image"]) as im:
            assert im.size == (r["width"], r["height"])
        assert r["license_uri"].startswith("https://") and r["flags"] == [] and (r["pair_id"] or r["control_kind"] == "extra")
        assert ("mining_class" in r) == (r["group"] == "error") and ("control_glyph" in r) == (r["group"] == "control")
    by_id = {r["id"]: r for r in rows}
    assert by_id["s0-target"]["paper_id"] == "glyphforge/" + "ab" * 4
    assert by_id["s1-target"]["paper_id"] == "2101.00001"
    assert by_id["s0-hard_negative"]["control_glyph"] == "v" and by_id["s0-target"]["mining_class"] == "greek.upsilon_v@1"
    assert by_id["s1-target"]["latex"] == r"\bar{x}"
    extra = by_id["p0-c0"]
    assert extra["group"] == "control" and extra["control_glyph"] == "v" and extra["pair_id"] is None and extra["control_kind"] == "extra"


def test_manifest_and_errors(exported, tmp_path):
    out, manifest, samples = exported
    assert manifest == json.loads((out / "export_manifest.json").read_text())
    assert manifest["groups"] == {"control": 3, "error": 2} and manifest["n_rows"] == 5
    assert manifest["control_glyphs_used"] == {r"\overline": 1, "v": 2}
    assert manifest["licenses"] == {"CC-BY-4.0": 2, "CC0-1.0": 3}
    assert control_glyphs_used(samples) == manifest["control_glyphs_used"]
    assert str(tmp_path) not in (out / "trainset.jsonl").read_text() + (out / "export_manifest.json").read_text()
    with pytest.raises(FileExistsError):
        export_glyphfix(tmp_path / "store", out, base_dir=tmp_path)


def test_real_glyphfix_reader(exported):
    data = pytest.importorskip("glyphfix_math.train.data")
    trainset = pytest.importorskip("glyphfix_math.trainset")
    out, _, _ = exported
    rows = data.read_trainset(out / "trainset.jsonl")
    assert len(rows) == 5
    for r in rows:
        assert data.load_image(r, out).mode == "RGB"
    counts = trainset.summarize(rows)["counts"]["group"]
    assert counts["error"] == 2 and counts["control"] == 3
