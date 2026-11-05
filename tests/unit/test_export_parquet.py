import hashlib
import io
import json
import re

import numpy as np
import pytest
from PIL import Image

pq = pytest.importorskip("pyarrow.parquet")

from glyphforge import store
from glyphforge.export.parquet import COLUMNS, hf_features, parquet_row, write_parquet


def _sample(slot, licence="CC0-1.0"):
    arr = np.full((8 + slot, 12), 255, np.uint8)
    arr[3:5, 3 : 3 + slot % 7 + 1] = 0
    png = store.png_bytes(arr)
    by = licence.startswith("CC-BY")
    row = dict.fromkeys(store.SAMPLE_KEYS)
    row.update(
        authors=["A. Author"] if by else [], bitmap_sha256="b" * 64, class_version="1", env="equation*", error_class="greek.upsilon_v@1",
        family="greek", flags=["x"], generator_version="0.1.0", height=arr.shape[0], image="images/xx/y.png",
        image_digest="sha256:x", image_sha256=hashlib.sha256(png).hexdigest(), label="v", licence=licence, pair_id=f"p{slot}",
        paper_id="2101.00001" if by else None, paper_version="v1" if by else None, recipe_sha256="ab" * 32, role="target",
        rules={"a": 1}, sample_id=f"s{slot:04d}", seed=2**64 - 1 - slot, slot=slot, style="default", style_preamble_sha256="s" * 64,
        width=arr.shape[1], source_canon="v", attempt=0, column_cm=None, font="cm", n_sites=1, n_tokens=3, pad_px=0, site_level="base",
        size_pt=12, source="list", structure="display", wrapper="display",
    )  # fmt: skip
    return row, png


@pytest.fixture
def parts():
    return [_sample(i, "CC-BY-4.0" if i % 2 else "CC0-1.0") for i in range(6)]


def _rows(parts):
    return [parquet_row(s, png, []) for s, png in parts]


def test_row_keys_and_attribution(parts):
    s, png = parts[1]
    row = parquet_row(s, png, [{"op": "blur"}])
    assert set(row) == set(store.SAMPLE_KEYS) - {"licence"} | {"license", "license_uri", "attribution", "arxiv_id", "degrade_ops"}
    assert set(row) == {n for n, _ in COLUMNS}
    assert row["image"] == {"bytes": png, "path": None}
    assert json.loads(row["rules"]) == {"a": 1} and json.loads(row["degrade_ops"]) == [{"op": "blur"}]
    assert row["attribution"] == (
        "arXiv:2101.00001v1, A. Author; CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/); "
        "modified: synthetic glyph substitutions, re-rendered by GlyphForge"
    )
    assert row["arxiv_id"] == "2101.00001"
    cc0 = parquet_row(*parts[0], [])
    assert cc0["arxiv_id"] is None and "CC0-1.0" in cc0["attribution"] and cc0["degrade_ops"] == "[]"


def test_single_and_multiple_shards(tmp_path, parts):
    names = write_parquet(tmp_path / "a", _rows(parts), shard_bytes=10**9, row_group_rows=2)
    assert names == ["data/train-00000-of-00001.parquet"]
    names = write_parquet(tmp_path / "b", _rows(parts), shard_bytes=1, row_group_rows=2)
    assert names == [f"data/train-{i:05d}-of-00006.parquet" for i in range(6)]
    assert not list((tmp_path / "b" / "data").glob(".shard-*"))
    assert sum(pq.read_metadata(tmp_path / "b" / n).num_rows for n in names) == 6


def test_empty_writes_one_shard(tmp_path):
    names = write_parquet(tmp_path, [], shard_bytes=10, row_group_rows=2)
    assert names == ["data/train-00000-of-00001.parquet"]
    assert pq.read_metadata(tmp_path / names[0]).num_rows == 0


def test_schema_metadata_and_clean_footer(tmp_path, parts):
    (name,) = write_parquet(tmp_path, _rows(parts), shard_bytes=10**9, row_group_rows=4)
    f = tmp_path / name
    meta = pq.read_schema(f).metadata
    assert json.loads(meta[b"huggingface"]) == {"info": {"features": hf_features()}}
    assert set(pq.read_metadata(f).metadata) <= {b"huggingface", b"ARROW:schema"}
    assert pq.read_schema(f).field("seed").type.equals(__import__("pyarrow").uint64())
    blob = f.read_bytes()
    assert not re.search(rb"/home/|/mnt/|/Users/|[\w.]+@[\w.]+\.\w+", blob)
    table = pq.read_table(f)
    for col in table.column_names:
        if str(table.schema.field(col).type) == "string":
            assert not any(re.search(r"/home/|/mnt/|/Users/|[\w.]+@[\w.]+\.\w+", v or "") for v in table[col].to_pylist())


def test_deterministic(tmp_path, parts):
    a = write_parquet(tmp_path / "a", _rows(parts), shard_bytes=300, row_group_rows=2)
    b = write_parquet(tmp_path / "b", _rows(parts), shard_bytes=300, row_group_rows=2)
    assert a == b
    for n in a:
        assert hashlib.sha256((tmp_path / "a" / n).read_bytes()).digest() == hashlib.sha256((tmp_path / "b" / n).read_bytes()).digest()


def test_hf_roundtrip(tmp_path, parts):
    datasets = pytest.importorskip("datasets")
    names = write_parquet(tmp_path, _rows(parts), shard_bytes=300, row_group_rows=2)
    files = sorted(str(tmp_path / n) for n in names)
    feats = datasets.Features.from_arrow_schema(pq.read_schema(files[0]))
    assert feats == datasets.Features.from_dict(hf_features())
    assert feats.to_dict() == hf_features()
    ds = datasets.load_dataset("parquet", data_files=files, split="train", cache_dir=str(tmp_path / "cache"))
    assert isinstance(ds.features["image"], datasets.Image)
    raw = ds.cast_column("image", datasets.Image(decode=False))
    assert [r["image"]["bytes"] for r in raw] == [png for _, png in parts]
    assert np.array_equal(np.asarray(ds[0]["image"]), np.asarray(Image.open(io.BytesIO(parts[0][1]))))
