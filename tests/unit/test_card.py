import re

from glyphforge.export.card import NO_ENDORSE, attribution_text, dataset_card, pick_pairs

RUN = {"canon_versions": {"normalize": 3}, "render_config": {"dpi": 300}, "pixel_policy_version": 2, "seed": 7, "classes": []}
MANIFEST = {
    "format": "parquet", "n_rows": 3, "roles": {"target": 2, "hard_negative": 1}, "sources": {"list": 2, "grammar": 1},
    "licenses": {"CC0-1.0": 1, "CC-BY-4.0": 2}, "recipe_sha256": "ab" * 32, "generator_version": "0.1.0", "image_digest": "sha256:dig",
    "blocklist": {"path": "blocklist.jsonl", "sha256": "cd" * 32, "formulas": 12, "papers": 7}, "leak_policy": "Any exact canon match fails the export.",
    "degrade": None, "degrade_sha256": None, "shards": ["data/train-00000-of-00001.parquet"], "pyarrow_version": "26.0.1",
    "pillow_version": "12.3.0", "numpy_version": "2.5.0", "zlib_version": "1.3",
    "error_classes": {"prime": 2, "none": 1}, "fonts": {"newtx": 3}, "empty_cells": [],
    "grid": [{"error_class": "prime", "font": "newtx", "target": "assets/pair-00-error.png", "control": "assets/pair-00-control.png",
              "target_label": "a|b<", "control_label": "c"}],
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
    assert card.startswith("---\npretty_name: GlyphForge synthetic formula images\nlicense:\n- cc-by-4.0\n- cc0-1.0\n")
    assert "config_name: default" in card and "path: data/train-*.parquet" in card
    for needle in ("sha256:dig", "cd" * 32, "Any exact canon match fails the export.", "blocklist.jsonl", "ab" * 32, "0.1.0", '"normalize": 3',
                   "| CC-BY-4.0 | 2 |", "\n3 rendered", NO_ENDORSE, "[GlyphForge](https://github.com/ogaude/glyphforge) 0.1.0",
                   "https://github.com/ogaude/glyphforge/blob/v0.1.0/docs/reproducibility.md"):  # fmt: skip
        assert needle in card
    assert "\nnone\n" in card
    assert not re.search(r"\d{4}-\d{2}-\d{2}", card)
    assert not re.search(r"/home/|/mnt/|/Users/", card)


def test_card_licence_wording_follows_licences_and_leakage_is_a_sentence():
    both = dataset_card(RUN, MANIFEST)
    assert "Rows under CC0-1.0" in both and "CC BY licence are derivatives" in both and "Grammar rows are dedicated" not in both
    assert "12 formulas and 7 papers" in both
    cc0 = dataset_card(RUN, MANIFEST | {"licenses": {"CC0-1.0": 3}})
    assert "CC BY" not in cc0.split("## Rendering")[0].split("## Licensing")[1]
    text = attribution_text([_s("2101.00001", "v1", "CC0-1.0", ["A"])])
    assert "derived from CC0-licensed papers" in text and "Grammar rows" not in text


def test_leak_policy_text_is_capitalised():
    from glyphforge.export.deliver import LEAK_POLICY

    assert LEAK_POLICY[0].isupper()


def _p(i, role, cls, font, pid):
    return {"sample_id": f"{pid}-{role}", "pair_id": pid, "role": role, "control_kind": "pair", "error_class": cls, "font": font}


def test_pick_pairs_round_robin_and_missing():
    rows = [_p(i, r, c, f, f"p{i}") for i, (c, f) in enumerate([("a", "x"), ("a", "x"), ("b", "y")]) for r in ("target", "hard_negative")]
    picked, missing = pick_pairs(rows, ["x", "y"], 3)
    assert [p["target"]["pair_id"] for p in picked] == ["p0", "p2", "p1"]
    assert missing == [("a", "y"), ("b", "x")]
    assert (picked, missing) == pick_pairs(rows, ["x", "y"], 3)


def test_attribution_lists_cc0_papers_and_verbatim_wording():
    text = attribution_text([_s("2101.00003", "v1", "CC0-1.0", ["Z"]), _s(None, None, "CC0-1.0", [])], derived=False)
    assert "arXiv:2101.00003v1; Z; CC0-1.0" in text and "formulas: 1" in text and "modified" not in text and "Rows: 2." in text


def test_card_extended_sections_and_hub_variant():
    card = dataset_card(RUN, MANIFEST)
    for needle in ("size_categories:\n- n<1K", "annotations_creators:\n- machine-generated", "tags:", "## Limitations", "## Intended use", "## Citation",
                   "| error class | rows |", "| font | rows |", "![error](assets/pair-00-error.png)", "a&#124;b&lt;",
                   "GlyphForge: a synthetic LaTeX formula generator with verified labels"):  # fmt: skip
        assert needle in card
    assert "load_dataset(" not in card and "glyphforge-equations:" not in card
    hub = dataset_card(RUN, MANIFEST, repo_id="ogaude/glyphforge-equations")
    assert 'load_dataset("ogaude/glyphforge-equations", split="train")' in hub
    assert "hf download ogaude/glyphforge-equations --repo-type dataset" in hub and "glyphforge-equations: synthetic LaTeX" in hub
    assert not re.search(r"\d{4}-\d{2}-\d{2}|/home/|/mnt/|/Users/", hub)


def test_size_category_thresholds():
    for n, cat in ((3, "n<1K"), (5_000, "1K<n<10K"), (99_999, "10K<n<100K"), (100_000, "100K<n<1M")):
        assert f"size_categories:\n- {cat}\n" in dataset_card(RUN, MANIFEST | {"n_rows": n})


def test_card_degrade_spec():
    card = dataset_card(RUN, MANIFEST | {"degrade": {"blur": {"p": 0.5}}, "degrade_sha256": "ee" * 32})
    assert '"blur"' in card and "ee" * 32 in card
