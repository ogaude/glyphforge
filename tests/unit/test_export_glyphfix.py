import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from glyphforge import store
from glyphforge.export import control_glyphs_used, export_glyphfix
from glyphforge.export.glyphfix import ROLE_GROUP

REQUIRED_KEYS = ("id", "paper_id", "image", "latex", "target_text", "group", "width", "height")
FENCE = "`" * 3


def _sample(slot, role, label, cls, glyph, licence, arr):
    png = store.png_bytes(arr)
    sha = hashlib.sha256(png).hexdigest()
    by = licence.startswith("CC-BY")
    row = dict.fromkeys(store.SAMPLE_KEYS)
    row.update(
        authors=["A. Author"] if by else [], bitmap_sha256="b" * 64, class_version=1, env="equation*", error_class=cls, family=cls.split(".")[0],
        flags=[], generator_version="0.1.0", height=arr.shape[0], image=f"images/{sha[:2]}/{sha}.png", image_digest="sha256:x", image_sha256=sha,
        label=label, licence=licence, pair_id=f"p{slot}", paper_id="2101.00001" if by else None, paper_version="v1" if by else None,
        recipe_sha256="ab" * 32, role=role, rules={}, sample_id=f"s{slot}-{role}", seed=slot, slot=slot, style="default",
        style_preamble_sha256="s" * 64, width=arr.shape[1],
        control_glyph=glyph if role == "hard_negative" else None,
    )
    return row, {sha: png}


@pytest.fixture
def exported(tmp_path):
    a, b = np.full((8, 12), 255, np.uint8), np.full((9, 14), 255, np.uint8)
    a[3:5, 3:9] = 0
    b[2:7, 4:10] = 0
    parts = [
        _sample(0, "target", r"\upsilon", "greek.upsilon_v@1", None, "CC0-1.0", a),
        _sample(0, "hard_negative", "v", "greek.upsilon_v@1", "v", "CC0-1.0", b),
        _sample(1, "target", r"\bar{x}", "decorations.bar_overline@1", None, "CC-BY-4.0", a),
        _sample(1, "hard_negative", r"\overline{x}", "decorations.bar_overline@1", r"\overline", "CC-BY-4.0", b),
    ]
    samples = [p[0] for p in parts]
    images = {k: v for _, im in parts for k, v in im.items()}
    ledger = [{"error_class": s["error_class"], "label": s["label"], "pair_id": s["pair_id"], "reason": None, "role": s["role"], "slot": s["slot"],
               "style": "default"} for s in samples]
    store.write_store(tmp_path / "store", samples, images, ledger, {"recipe_sha256": "ab" * 32})
    manifest = export_glyphfix(tmp_path / "store", tmp_path / "out")
    return tmp_path / "out", manifest, samples


def _rows(out):
    return [json.loads(line) for line in (out / "trainset.jsonl").read_text().splitlines()]


def test_vendored_contract(exported):
    out, _, _ = exported
    rows = _rows(out)
    assert len(rows) == 4
    for r in rows:
        assert all(k in r for k in REQUIRED_KEYS)
        assert r["target_text"] == FENCE + "latex\n" + r["latex"] + "\n" + FENCE
        assert r["group"] == ROLE_GROUP["target" if r["group"] == "error" else "hard_negative"]
        with Image.open(out / r["image"]) as im:
            assert im.size == (r["width"], r["height"])
        assert r["license_uri"].startswith("https://") and r["pair_id"] and r["flags"] == []
        assert ("mining_class" in r) == (r["group"] == "error") and ("control_glyph" in r) == (r["group"] == "control")
    by_id = {r["id"]: r for r in rows}
    assert by_id["s0-target"]["paper_id"] == "glyphforge/" + "ab" * 4
    assert by_id["s1-target"]["paper_id"] == "2101.00001"
    assert by_id["s0-hard_negative"]["control_glyph"] == "v" and by_id["s0-target"]["mining_class"] == "greek.upsilon_v@1"
    assert by_id["s1-target"]["latex"] == r"\bar{x}"


def test_manifest_and_errors(exported, tmp_path):
    out, manifest, samples = exported
    assert manifest == json.loads((out / "export_manifest.json").read_text())
    assert manifest["groups"] == {"control": 2, "error": 2} and manifest["n_rows"] == 4
    assert manifest["control_glyphs_used"] == {r"\overline": 1, "v": 1}
    assert manifest["licenses"] == {"CC-BY-4.0": 2, "CC0-1.0": 2}
    assert control_glyphs_used(samples) == manifest["control_glyphs_used"]
    assert str(tmp_path) not in (out / "trainset.jsonl").read_text() + (out / "export_manifest.json").read_text()
    with pytest.raises(FileExistsError):
        export_glyphfix(tmp_path / "store", out)


def test_real_glyphfix_reader(exported):
    data = pytest.importorskip("glyphfix_math.train.data")
    trainset = pytest.importorskip("glyphfix_math.trainset")
    out, _, _ = exported
    rows = data.read_trainset(out / "trainset.jsonl")
    assert len(rows) == 4
    for r in rows:
        assert data.load_image(r, out).mode == "RGB"
    counts = trainset.summarize(rows)["counts"]["group"]
    assert counts["error"] == 2 and counts["control"] == 2
