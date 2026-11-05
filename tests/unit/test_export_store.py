import hashlib
import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from glyphforge.canon import canonical
from glyphforge.export import LeakError, export_parquet, export_store

PERSONAL = re.compile(r"/home/|/mnt/|/Users/|C:\\|[\w.+-]+@[\w-]+\.[\w.]+")
DEGRADE = {"contrast": {"p": 1, "min": 0.5, "max": 0.9}, "blur": {"p": 1, "min": 0.5, "max": 1.0}, "noise": {"p": 1, "min": 2, "max": 5}}


def scan_for_leaks(root: Path) -> list[str]:
    """Personal-path or email hits in text files, Parquet strings and footer, plus any PNG chunk beyond IHDR/IDAT/IEND."""
    bad = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix == ".png":
            data, pos, chunks = f.read_bytes(), 8, []
            while pos < len(data):
                chunks.append(data[pos + 4 : pos + 8])
                pos += 12 + int.from_bytes(data[pos : pos + 4], "big")
            if set(chunks) - {b"IHDR", b"IDAT", b"IEND"}:
                bad.append(f"{f}: chunks {chunks}")
        elif f.suffix == ".parquet":
            pq = pytest.importorskip("pyarrow.parquet")
            table = pq.read_table(f)
            texts = [v or "" for c in table.column_names if str(table.schema.field(c).type) == "string" for v in table[c].to_pylist()]
            texts += [v.decode() for v in pq.read_metadata(f).metadata.values()]
            bad += [f"{f}: {t[:40]}" for t in texts if PERSONAL.search(t)]
        elif PERSONAL.search(f.read_text("utf-8")):
            bad.append(str(f))
    return bad


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("fmt", ["glyphfix", "parquet"])
@pytest.mark.parametrize("hit", [("formula", "label"), ("formula", "src"), ("paper", "2101.00001")])
def test_leak_aborts_before_any_write(tmp_path, make_store, fmt, hit):
    kind, value = hit
    s = make_store(blocklist=[{"k": kind, "v": canonical(r"\upsilon") if value == "label" else value}])
    with pytest.raises(LeakError) as exc:
        export_store(s.store, tmp_path / "out", fmt, spec=s.spec, base_dir=s.base_dir)
    assert exc.value.hits
    assert not (tmp_path / "out").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bl.jsonl", "store"]


def test_spec_and_store_refusals(tmp_path, make_store):
    s = make_store()
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="export.blocklist"):
        export_store(s.store, out, "glyphfix", spec=s.spec.model_copy(update={"blocklist": None}), base_dir=s.base_dir)
    pin = s.spec.blocklist.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValueError, match="blocklist sha256 mismatch"):
        export_store(s.store, out, "glyphfix", spec=s.spec.model_copy(update={"blocklist": pin}), base_dir=s.base_dir)
    assert not out.exists()
    out.mkdir()
    (out / "keep").write_text("x")
    with pytest.raises(FileExistsError):
        export_store(s.store, out, "parquet", spec=s.spec, base_dir=s.base_dir)
    assert (out / "keep").read_text() == "x"


def test_old_schema_refused(tmp_path, make_store):
    s = make_store(schema_version=2)
    with pytest.raises(ValueError, match="schema 3"):
        export_store(s.store, tmp_path / "out", "glyphfix", spec=s.spec, base_dir=s.base_dir)


@pytest.mark.parametrize("fmt", ["glyphfix", "parquet"])
def test_deterministic_and_clean(tmp_path, make_store, fmt):
    s = make_store(degrade=DEGRADE)
    for name in ("a", "b"):
        export_store(s.store, tmp_path / name, fmt, base_dir=s.base_dir)
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")
    assert scan_for_leaks(tmp_path / "a") == []


def test_clean_export_passes_store_bytes_through(tmp_path, make_store):
    s = make_store()
    manifest = export_store(s.store, tmp_path / "g", "glyphfix", base_dir=s.base_dir)
    rows = [json.loads(line) for line in (tmp_path / "g" / "trainset.jsonl").read_text().splitlines()]
    assert all(r["degrade_ops"] == [] and (tmp_path / "g" / r["image"]).read_bytes() == (s.store / r["image"]).read_bytes() for r in rows)
    assert manifest["export_spec_from_store"] is True and manifest["degrade"] is None and manifest["degrade_sha256"] is None
    other = s.spec.model_copy(update={"shard_mb": 7})
    assert export_store(s.store, tmp_path / "g2", "glyphfix", spec=other, base_dir=s.base_dir)["export_spec_from_store"] is False


@pytest.mark.parametrize("fmt", ["glyphfix", "parquet"])
def test_degraded_rows_share_pair_ops(tmp_path, make_store, fmt):
    s = make_store(degrade=DEGRADE)
    manifest = export_store(s.store, tmp_path / "o", fmt, base_dir=s.base_dir)
    if fmt == "glyphfix":
        rows = [json.loads(line) for line in (tmp_path / "o" / "trainset.jsonl").read_text().splitlines()]
        by = {r["id"]: r for r in rows}
        ops = {k: r["degrade_ops"] for k, r in by.items()}
        for r in rows:
            png = (tmp_path / "o" / r["image"]).read_bytes()
            assert r["image"].endswith(f"{hashlib.sha256(png).hexdigest()}.png")
            assert Image.open(io.BytesIO(png)).size == (r["width"], r["height"])
    else:
        pq = pytest.importorskip("pyarrow.parquet")
        table = pq.read_table(tmp_path / "o" / manifest["shards"][0]).to_pylist()
        by = {r["sample_id"]: r for r in table}
        ops = {k: json.loads(r["degrade_ops"]) for k, r in by.items()}
        assert all(r["image_sha256"] == hashlib.sha256(r["image"]["bytes"]).hexdigest() for r in table)
        assert all(Image.open(io.BytesIO(r["image"]["bytes"])).size == (r["width"], r["height"]) for r in table)
        assert {r["bitmap_sha256"] for r in table} == {"b" * 64}
    assert ops["s0-target"] == ops["s0-hard_negative"] != [] and ops["s1-target"] == ops["s1-hard_negative"]
    assert ops["s0-target"] != ops["s1-target"] and ops["p0-c0"] not in ([], ops["s0-target"])
    assert manifest["degrade"] and re.fullmatch(r"[0-9a-f]{64}", manifest["degrade_sha256"])


def test_parquet_tree_manifest_and_roundtrip(tmp_path, make_store):
    s = make_store()
    manifest = export_parquet(s.store, tmp_path / "o", base_dir=s.base_dir)
    out = tmp_path / "o"
    assert sorted(_tree(out)) == ["ATTRIBUTION.md", "README.md", "data/train-00000-of-00001.parquet", "export_manifest.json"]
    assert manifest == json.loads((out / "export_manifest.json").read_text())
    assert {
        "export_spec",
        "export_spec_sha256",
        "export_spec_from_store",
        "pyarrow_version",
        "pillow_version",
        "numpy_version",
        "zlib_version",
    } <= set(manifest)
    assert manifest["blocklist"] == {"path": "bl.jsonl", "sha256": s.spec.blocklist.sha256} and manifest["leak_hits"] == 0
    assert "arXiv:2101.00001v1" in (out / "ATTRIBUTION.md").read_text()
    datasets = pytest.importorskip("datasets")
    ds = datasets.load_dataset("parquet", data_files=[str(out / manifest["shards"][0])], split="train", cache_dir=str(tmp_path / "cache"))
    assert isinstance(ds.features["image"], datasets.Image)
    raw = ds.cast_column("image", datasets.Image(decode=False))
    assert sorted(r["image"]["bytes"] for r in raw) == sorted((s.store / x["image"]).read_bytes() for x in s.samples)
