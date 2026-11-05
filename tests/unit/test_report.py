import json

from glyphforge.report import balance_report, scale_report


def _row(w=320, h=320, size=12, font="cm", structure="display", role="target", **kw):
    base = {
        "role": role, "width": w, "height": h, "size_pt": size, "font": font, "structure": structure, "column_cm": None,
        "env": "equation", "source": "grammar", "site_level": "base", "n_tokens": 20, "label": "x", "error_class": "prime",
    }  # fmt: skip
    return base | kw


def test_scale_upsize_and_flags():
    r = scale_report([_row(200, 60)])
    g = r["groups"]["cm|12|display"]
    assert g["upsized_share"] == 1.0 and g["mean_upsize"] == 2.4
    assert g["px_per_pt"]["policy"]["p50"] == round(300 / 72 * 2.4, 4)
    assert g["image_tokens"]["p50"] == 75
    assert r["counts"]["upsized"] == 1 and r["flags"]["64-token-min"] == 1


def test_scale_factor_and_non_upsized():
    g = scale_report([_row(470, 139), _row(811, 139, size=11)])["groups"]
    assert g["cm|12|display"]["mean_upsize"] == round(480 / 470, 4)
    assert g["cm|11|display"]["upsized_share"] == 0.0


def test_scale_policy_size_is_exact_and_references():
    r = scale_report([_row(320, 320)])
    assert r["groups"]["cm|12|display"]["px_per_pt"]["policy"]["p50"] == round(300 / 72, 4)
    refs = r["references"]
    assert refs["crop_300dpi"]["px_per_pt"] == round(300 / 72, 4)
    assert 1.07 < refs["page_a4"]["policy"] < 1.09
    assert 0.85 < refs["page_a4"]["train_cap"] < 0.90
    assert "corpus" not in refs
    assert any("scale gap" in w for w in r["warnings"])


def test_scale_corpus_and_json():
    r = scale_report([_row()], corpus={"width_q": [1], "height_q": [2], "area_below_floor": 0.237})
    assert r["references"]["corpus"]["area_below_floor"] == 0.237
    assert json.loads(json.dumps(r)) == r


def test_balance_matched_no_warning():
    rows = []
    for i in range(20):
        size, cls = (12 if i % 2 else 10), f"c{i % 4}"
        rows += [_row(size=size, error_class=cls), _row(size=size, role="hard_negative", error_class=cls)]
    r = balance_report(rows)
    assert r["warnings"] == [] and all(v == 0 for v in r["tv"].values())
    assert r["counts"] == {"targets": 20, "controls": 20}
    assert r["joint"]["c0|cm|10|display"] == {"controls": 5, "targets": 5}


def test_balance_leak_warns():
    rows = [_row(size=12) for _ in range(10)] + [_row(size=11, role="hard_negative") for _ in range(10)]
    r = balance_report(rows)
    assert r["tv"]["size_pt"] == 1.0
    assert "size_pt separates targets from controls (TV 1.00 > 0.10)" in r["warnings"]
    assert any("joint metadata predicts role" in w for w in r["warnings"])
    json.dumps(r)


def test_balance_empty():
    r = balance_report([])
    assert r["warnings"] == [] and r["counts"] == {"targets": 0, "controls": 0}
