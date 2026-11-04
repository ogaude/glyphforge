import hashlib
import io
import json

import numpy as np
import pytest
from PIL import Image

from glyphforge import store


def _crop():
    a = np.full((6, 9), 255, dtype=np.uint8)
    a[2:4, 3:6] = 0
    return a


def make_sample(slot, role, png, **over):
    sha = hashlib.sha256(png).hexdigest()
    row = dict.fromkeys(store.SAMPLE_KEYS)
    row.update(
        authors=[], bitmap_sha256="b" * 64, class_version=1, env="equation*", error_class="greek.upsilon_v@1", family="greek", flags=[],
        generator_version="0.1.0", height=6, image=f"images/{sha[:2]}/{sha}.png", image_digest="sha256:x", image_sha256=sha, label="v",
        licence="CC0-1.0", pair_id=f"p{slot}", recipe_sha256="r" * 64, role=role, rules={"canon": "1"}, sample_id=f"s{slot}-{role}", seed=slot,
        slot=slot, style="default", style_preamble_sha256="s" * 64, width=9,
    )
    if role == "hard_negative":
        row["control_glyph"] = "v"
    row.update(over)
    return row


def ledger_row(slot, role):
    return {"error_class": "c@1", "label": "v", "pair_id": f"p{slot}", "reason": None, "role": role, "slot": slot, "style": "default"}


def build(tmp_path):
    png = store.png_bytes(_crop())
    sha = hashlib.sha256(png).hexdigest()
    samples = [make_sample(1, "target", png), make_sample(0, "hard_negative", png), make_sample(0, "target", png)]
    ledger = [ledger_row(1, "target"), ledger_row(0, "target")]
    return tmp_path, samples, {sha: png}, ledger, {"recipe_sha256": "r" * 64}


def test_png_bytes_deterministic_and_clean():
    a = store.png_bytes(_crop())
    assert a == store.png_bytes(_crop())
    img = Image.open(io.BytesIO(a))
    assert img.mode == "L" and img.size == (9, 6) and not img.text
    with pytest.raises(ValueError):
        store.png_bytes(np.zeros((2, 2, 3), dtype=np.uint8))


def test_roundtrip_sorted_and_compact(tmp_path):
    out, samples, images, ledger, run = build(tmp_path / "a")
    store.write_store(out, samples, images, ledger, run)
    got_run, got_samples, got_ledger = store.read_store(out)
    assert got_run == run
    assert [(s["slot"], s["role"]) for s in got_samples] == [(0, "hard_negative"), (0, "target"), (1, "target")]
    assert [r["slot"] for r in got_ledger] == [0, 1]
    line = (out / "samples.jsonl").read_text().splitlines()[0]
    assert ", " not in line and line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert (out / "run.json").read_text().endswith("}\n")
    sha = next(iter(images))
    assert (out / "images" / sha[:2] / f"{sha}.png").read_bytes() == images[sha]


def test_byte_identical_trees(tmp_path):
    for name in ("a", "b"):
        out, *rest = build(tmp_path / name)
        store.write_store(out, *rest)
    files = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*") if p.is_file())
    assert files and all((tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes() for f in files)


def test_validation(tmp_path):
    out, samples, images, ledger, run = build(tmp_path)
    bad = dict(samples[0])
    bad.pop("seed")
    bad["extra"] = 1
    with pytest.raises(ValueError, match="missing.*seed"):
        store.write_store(out, [bad], images, ledger, run)
    with pytest.raises(ValueError, match="ledger"):
        store.write_store(out, samples, images, [{"slot": 0}], run)
    with pytest.raises(ValueError, match="sha256"):
        store.write_store(out, samples, {"zz": b"x"}, ledger, run)
    with pytest.raises(ValueError, match="image path"):
        store.write_store(out, [{**samples[0], "image": "images/xx/yy.png"}], images, ledger, run)
    assert not (out / "run.json").exists()


def test_incomplete_and_existing(tmp_path):
    with pytest.raises(FileNotFoundError, match="incomplete store: run.json missing"):
        store.read_store(tmp_path)
    store.write_store(*build(tmp_path))
    with pytest.raises(FileExistsError):
        store.write_store(*build(tmp_path))
