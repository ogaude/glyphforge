import hashlib

import numpy as np
import pytest
import yaml

from glyphforge import store
from glyphforge.preview import preview_html, preview_recipe
from glyphforge.recipe import DegradeSpec, Recipe

RECIPE = Recipe(styles=[{"name": "cm", "font": "cm", "size": 12}, {"name": "lib", "font": "libertine", "size": 12}])


def _pair(slot, cls, font, label, hard):
    rows, images = [], {}
    for role, text, fill in (("target", label, 0), ("hard_negative", hard, 90)):
        png = store.png_bytes(np.full((8, 12), 255, np.uint8) - fill)
        sha = hashlib.sha256(png).hexdigest()
        images[sha] = png
        row = dict.fromkeys(store.SAMPLE_KEYS)
        row.update(image=f"images/{sha[:2]}/{sha}.png", image_sha256=sha, pair_id=f"p{slot}", role=role, control_kind="pair", slot=slot, attempt=0,
                   sample_id=f"s{slot}-{role}", label=text, error_class=cls, font=font)  # fmt: skip
        rows.append(row)
    return rows, images


def _store(tmp_path, specs, export=None):
    parts = [_pair(i, *spec) for i, spec in enumerate(specs)]
    samples = [r for rows, _ in parts for r in rows]
    images = {k: v for _, im in parts for k, v in im.items()}
    ledger = [{k: r.get(k) for k in store.LEDGER_KEYS} for r in samples]
    recipe = RECIPE.model_dump(mode="json")
    recipe["export"] = {**recipe["export"], **(export or {})}
    store.write_store(tmp_path / "store", samples, images, ledger, {"seed": 7, "recipe": recipe})
    return tmp_path / "store"


def _rows(html):
    return html.count("<tr>") - 1


SPECS = [
    ("greek.upsilon_v@1", "cm", "x<y & z", "w"),
    ("greek.upsilon_v@1", "cm", "x2", "w2"),
    ("greek.upsilon_v@1", "cm", "x3", "w3"),
    ("primes.prime_l@1", "cm", "p", "q"),
    ("greek.upsilon_v@1", "libertine", "u", "v"),
]


def test_self_contained_escaped_and_stratified(tmp_path):
    html = preview_html(_store(tmp_path, SPECS), pairs=3)
    assert "http" not in html and "<script" not in html and html.count("data:image/png;base64,") == 6
    assert _rows(html) == 3  # one pair per present cell
    assert "not sampled: primes.prime_l@1/libertine" in html
    assert preview_html(_store(tmp_path / "b", SPECS), pairs=3) == html  # deterministic


def test_label_escaping(tmp_path):
    html = preview_html(_store(tmp_path, SPECS), pairs=48)
    assert "x&lt;y &amp; z" in html and "x<y" not in html and "<code>x<" not in html and _rows(html) == 5


def test_degraded_column_only_with_spec(tmp_path):
    root = _store(tmp_path, SPECS[:1])
    assert "degraded" not in preview_html(root)
    spec = DegradeSpec(blur={"p": 1})
    html = preview_html(root, degrade=spec)
    assert "degraded target" in html and "&quot;op&quot;: &quot;blur&quot;" in html and html.count("data:image/png;base64,") == 4
    stored = preview_html(_store(tmp_path / "s", SPECS[:1], {"degrade": spec.model_dump(mode="json")}))
    assert "degraded target" in stored


def test_recipe_preview_oversamples_and_leaves_no_export(tmp_path, fake):
    path = tmp_path / "r.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["a_{v}+v", "b+v+c", "v-d", "e*v", "v+f", "2v+g"]},
                "classes": ["greek.upsilon_v"],
                "styles": [{"name": "cm", "font": "cm", "size": 12}, {"name": "lib", "font": "libertine", "size": 12}],
                "composition": {"total": 50},
            }
        ),
        encoding="utf-8",
    )
    html = preview_recipe(path, pairs=4, cache=tmp_path / "cache")
    assert 1 <= _rows(html) <= 4
    assert {"cm", "libertine"} <= {f for f in ("cm", "libertine") if f"<td>{f}</td>" in html}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cache", "r.yaml"]


def test_preview_html_requires_store(tmp_path):
    with pytest.raises(FileNotFoundError):
        preview_html(tmp_path)
