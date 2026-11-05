import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from glyphforge.export.card import NO_ENDORSE, attribution_text, dataset_card

SPEC = importlib.util.spec_from_file_location("publish_hf", Path(__file__).resolve().parents[2] / "scripts" / "publish_hf.py")
ph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ph)

RUN = {"canon_versions": {"normalize": 3}, "render_config": {"dpi": 300}, "pixel_policy_version": 2, "seed": 7, "classes": []}
ROWS = [
    {
        "paper_id": "2101.00001",
        "paper_version": "v1",
        "licence": "CC-BY-4.0",
        "authors": ["A"],
        "latex": "x",
        "env": "equation",
        "split": "train",
    },
    {
        "paper_id": "2101.00002",
        "paper_version": "v2",
        "licence": "CC0-1.0",
        "authors": ["B"],
        "latex": "y",
        "env": "equation",
        "split": "train",
    },
]


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    src = tmp_path / "rec" / "source"
    src.mkdir(parents=True)
    snap = _write(src / "snap.jsonl", "".join(json.dumps(r) + "\n" for r in ROWS))
    block = _write(src / "block.jsonl", '{"canon": "z"}\n')
    _write(src / "snap.meta.json", json.dumps({"sha256": snap}))
    _write(src / "block.meta.json", json.dumps({"sha256": block}))
    recipe = tmp_path / "rec" / "r.yaml"
    recipe.write_text(
        "schema_version: 3\nsource:\n  kind: mix\n  parts:\n    - kind: grammar\n    - kind: mutation\n      path: source/snap.jsonl\n"
        f"      sha256: {snap}\nexport:\n  formats: [parquet]\n  blocklist:\n    path: source/block.jsonl\n    sha256: {block}\n",
        encoding="utf-8",
    )
    manifest = {
        "format": "hf-parquet", "n_rows": 3, "roles": {"target": 2, "hard_negative": 1}, "sources": {"grammar": 1, "mutation": 2},
        "licenses": {"CC0-1.0": 1, "CC-BY-4.0": 2}, "recipe_sha256": "ab" * 32, "generator_version": "0.1.0", "image_digest": "sha256:dig",
        "blocklist": {"path": "source/block.jsonl", "sha256": block, "formulas": 1, "papers": 1}, "leak_policy": "Any match fails.",
        "degrade": None, "degrade_sha256": None, "shards": ["data/train-00000-of-00001.parquet"], "pyarrow_version": "26", "pillow_version": "12",
        "numpy_version": "2", "zlib_version": "1", "error_classes": {"a": 3}, "fonts": {"cm": 3}, "empty_cells": [], "grid": [],
    }  # fmt: skip
    export = tmp_path / "export"
    (export / "data").mkdir(parents=True)
    (export / "assets").mkdir()
    (export / "data" / "train-00000-of-00001.parquet").write_bytes(b"PAR1")
    (export / "assets" / "pair-00-error.png").write_bytes(b"png")
    (export / "ATTRIBUTION.md").write_text("# Attribution\n", encoding="utf-8")
    (export / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    (store / "run.json").write_text(json.dumps(RUN), encoding="utf-8")
    return export, store, recipe, manifest, tmp_path / "stage"


@pytest.fixture
def staged(inputs):
    export, store, recipe, _, out = inputs
    return ph.stage(export, store, recipe, out), recipe


def test_stage_layout_and_card(staged, inputs):
    out, _recipe = staged
    names = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    assert names == {
        "README.md", "ATTRIBUTION.md", "export_manifest.json", "data/train-00000-of-00001.parquet", "assets/pair-00-error.png",
        "source/snap.jsonl", "source/snap.meta.json", "source/block.jsonl", "source/block.meta.json", "source/SNAPSHOT-ATTRIBUTION.md",
    }  # fmt: skip
    assert (out / "README.md").read_text(encoding="utf-8") == dataset_card(RUN, inputs[3], repo_id=ph.REPO_ID)
    assert (out / "source/SNAPSHOT-ATTRIBUTION.md").read_text(encoding="utf-8") == attribution_text(ROWS, derived=False)


def test_stage_refuses_existing_out_and_bad_pin(inputs):
    export, store, recipe, _, out = inputs
    out.mkdir()
    with pytest.raises(SystemExit):
        ph.stage(export, store, recipe, out)
    (recipe.parent / "source" / "snap.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ph.stage(export, store, recipe, out.parent / "other")


def test_audit_clean(staged):
    out, recipe = staged
    assert ph.audit(out, recipe) == [] == ph.audit(out)


@pytest.mark.parametrize("needle", ["me@" + "gmail" + ".com", str(ph.ROOT), str(Path.home()) + "/x", "/mnt/" + "datas/x"])
def test_audit_flags_personal_data(staged, needle):
    out, _ = staged
    (out / "ATTRIBUTION.md").write_text(f"# Attribution\n{needle}\n", encoding="utf-8")
    assert any("ATTRIBUTION.md" in p for p in ph.audit(out))


def test_audit_lighton(staged):
    out, _ = staged
    readme = out / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nBuilt for LightOn users.\n", encoding="utf-8")
    problems = ph.audit(out)
    assert len(problems) == 1 and "brand mention" in problems[0] and NO_ENDORSE not in problems[0]


def test_audit_licence_mismatch_and_pin(staged):
    out, recipe = staged
    readme = out / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("- cc0-1.0\n", ""), encoding="utf-8")
    assert any("licence" in p for p in ph.audit(out))
    (out / "source" / "snap.jsonl").write_text("{}\n", encoding="utf-8")
    assert any("snap.jsonl" in p for p in ph.audit(out, recipe))


def _fake_hub(monkeypatch):
    calls = []

    class Api:
        def create_repo(self, *a, **k):
            calls.append(("create_repo", a, k))

        def upload_folder(self, **k):
            calls.append(("upload_folder", k))

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=Api))
    return calls


def test_upload_private_and_audited(staged, monkeypatch):
    out, _ = staged
    calls = _fake_hub(monkeypatch)
    assert ph.upload(out, "u/r", ["source/*"]) == 0
    assert calls[0][2] == {"repo_type": "dataset", "private": True, "exist_ok": True}
    assert (
        calls[1][1]["allow_patterns"] == ["source/*"]
        and calls[1][1]["commit_message"] == "glyphforge-equations 0.1.0 (recipe " + "ab" * 6 + ")"
    )


def test_upload_refuses_failed_audit(staged, monkeypatch):
    out, _ = staged
    (out / "ATTRIBUTION.md").write_text("me@" + "gmail" + ".com\n", encoding="utf-8")
    calls = _fake_hub(monkeypatch)
    assert ph.upload(out, "u/r") == 1 and calls == []


def test_script_import_is_hub_free():
    src = Path(ph.__file__).read_text(encoding="utf-8")
    assert not any(
        line.startswith(("import huggingface_hub", "from huggingface_hub", "import datasets", "from datasets")) for line in src.splitlines()
    )
