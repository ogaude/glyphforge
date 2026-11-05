import json

import pytest

from glyphforge import pipeline
from glyphforge.pipeline import plan_run, run

FORMS = ["a_{v}+v", "b+v+c", "v-d", "e*v", "v+f", "2v+g", "h+v"]


def _recipe(**kw):
    return {
        "seed": 3,
        "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": FORMS},
        "classes": ["greek.upsilon_v", "greek.nu_v"],
        "styles": [{"name": "default", "font": "cm", "size": 12}],
        "structure": {"kinds": {"display": 1.0}},
        "composition": {"total": 6},
        **kw,
    }


def test_plan_counts_equal_round_zero_and_nothing_written(tmp_path, fake, monkeypatch):
    r = _recipe()
    res = run(r, tmp_path / "out", cache=tmp_path / "c")
    # 6 slots < SLOTS_PER_RENDER and one wrapper: the first render call is the whole of round 0
    round0 = len(fake[0][1])

    def boom(*a, **k):
        raise AssertionError("render_many called")

    monkeypatch.setattr(pipeline, "render_many", boom)
    before = set(tmp_path.rglob("*"))
    plan = plan_run(r, max_parallel=2)
    assert set(tmp_path.rglob("*")) == before
    assert plan == plan_run(r, max_parallel=2)
    json.dumps(plan)
    assert plan["recipe_sha256"] == res.recipe_sha256
    assert plan["totals"]["render_jobs"] == round0
    assert plan["totals"]["slots"] == 6 and plan["totals"]["undrawable_slots"] == 0
    assert sum(q["rows"] for q in plan["quotas"]) == plan["totals"]["rows"]
    assert all(q["rows"] == 2 * q["pairs"] + q["extra_controls"] for q in plan["quotas"])
    assert plan["estimate"]["rough"] and plan["estimate"]["workers"] == 2 and plan["attempt_cap"] >= 1


def test_progress_is_output_neutral(tmp_path, fake, tree):
    seen = []
    run(_recipe(), tmp_path / "a", cache=tmp_path / "ca")
    run(_recipe(), tmp_path / "b", cache=tmp_path / "cb", progress=lambda k, n: seen.append((k, n)))
    assert tree(tmp_path / "a") == tree(tmp_path / "b")
    assert seen and all(n == 6 for _, n in seen) and [k for k, _ in seen] == sorted(k for k, _ in seen)


def test_plan_rejects_unknown_class():
    with pytest.raises(ValueError):
        plan_run(_recipe(classes=["nope.nope"]))
