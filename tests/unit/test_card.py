import re

from glyphforge.export.card import attribution_text, dataset_card

RUN = {"canon_versions": {"normalize": 3}, "render_config": {"dpi": 300}, "pixel_policy_version": 2, "seed": 7, "classes": []}
MANIFEST = {
    "format": "parquet", "n_rows": 3, "roles": {"target": 2, "hard_negative": 1}, "sources": {"list": 2, "grammar": 1},
    "licenses": {"CC0-1.0": 1, "CC-BY-4.0": 2}, "recipe_sha256": "ab" * 32, "generator_version": "0.1.0", "image_digest": "sha256:dig",
    "blocklist": {"path": "blocklist.jsonl", "sha256": "cd" * 32}, "leak_policy": "Any exact canon match fails the export.",
    "degrade": None, "degrade_sha256": None, "shards": ["data/train-00000-of-00001.parquet"], "pyarrow_version": "26.0.1",
    "pillow_version": "12.3.0", "numpy_version": "2.5.0", "zlib_version": "1.3",
}  # fmt: skip


def _s(pid, ver, lic, authors):
    return {"paper_id": pid, "paper_version": ver, "licence": lic, "authors": authors}


def test_attribution_entries():
    text = attribution_text([
        _s("2101.00002", "v2", "CC-BY-4.0", ["B", "C"]), _s("2101.00001", "v1", "CC-BY-4.0", ["A"]),
        _s("2101.00001", "v1", "CC-BY-4.0", ["A"]), _s(None, None, "CC0-1.0", []),
    ])  # fmt: skip
    assert text.index("arXiv:2101.00001v1") < text.index("arXiv:2101.00002v2")
    assert "derived rows: 2" in text and "; B, C;" in text
    assert "https://creativecommons.org/licenses/by/4.0/" in text
    assert "modified: synthetic glyph substitutions, re-rendered by GlyphForge" in text
    assert "CC0-1.0" in text and "Rows: 1." in text
    assert "title" not in text.lower()


def test_attribution_cc0_only():
    text = attribution_text([_s(None, None, "CC0-1.0", [])])
    assert "CC0-1.0" in text and "arXiv:" not in text


def test_card_content_and_determinism():
    card = dataset_card(RUN, MANIFEST)
    assert card == dataset_card(RUN, MANIFEST)
    assert card.startswith("---\nlicense:\n- cc-by-4.0\n- cc0-1.0\n")
    assert "config_name: default" in card and "path: data/train-*.parquet" in card
    for needle in ("sha256:dig", "cd" * 32, "Any exact canon match fails the export.", "blocklist.jsonl", "ab" * 32, "0.1.0", '"normalize": 3',
                   "| CC-BY-4.0 | 2 |", "\n3 rendered", "not made or endorsed by LightOn"):  # fmt: skip
        assert needle in card
    assert "\nnone\n" in card
    assert not re.search(r"\d{4}-\d{2}-\d{2}", card)
    assert not re.search(r"/home/|/mnt/|/Users/", card)


def test_card_degrade_spec():
    card = dataset_card(RUN, MANIFEST | {"degrade": {"blur": {"p": 0.5}}, "degrade_sha256": "ee" * 32})
    assert '"blur"' in card and "ee" * 32 in card
