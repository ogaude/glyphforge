import json

import pytest

from glyphforge import pipeline
from glyphforge.pipeline import run
from glyphforge.store import JOURNAL, read_journal, write_round

RECIPE = {
    "seed": 3,
    "source": {"kind": "inline", "licence": "CC0-1.0", "formulas": ["v+a", r"v+\fail", r"v+\fail+b", r"v+\fail+c"]},
    "classes": ["greek.upsilon_v"],
    "styles": [{"name": "default", "font": "cm", "size": 12}],
    "structure": {"kinds": {"display": 1.0}},
    "composition": {"total": 6},
}


def _go(tmp_path, name, recipe=RECIPE):
    return run(recipe, tmp_path / name, cache=tmp_path / f"c-{name}")


@pytest.fixture
def kill(monkeypatch, fake):
    """Make the Nth render_many call raise; ``kill(None)`` disarms it."""
    real, state = pipeline.render_many, {"n": 0, "on": None}

    def render(*a, **kw):
        state["n"] += 1
        if state["n"] == state["on"]:
            raise RuntimeError("killed")
        return real(*a, **kw)

    monkeypatch.setattr(pipeline, "render_many", render)

    def arm(on):
        state["n"], state["on"] = 0, on

    return arm


def _rounds(out):
    return sorted((out / JOURNAL).glob("round-*.json"))


def test_resumed_run_is_byte_identical(tmp_path, tree, kill):
    _go(tmp_path, "a")
    ta = tree(tmp_path / "a")
    assert json.loads(ta["run.json"])["attempts"]["rounds"] >= 3
    assert not any(JOURNAL in k for k in ta) and b"resum" not in ta["run.json"]
    kill(3)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    assert not (tmp_path / "b" / "run.json").exists() and len(_rounds(tmp_path / "b")) == 2
    kill(None)
    _go(tmp_path, "b")
    assert tree(tmp_path / "b") == ta


def test_interrupt_before_first_commit_equals_plain_run(tmp_path, tree, kill):
    _go(tmp_path, "a")
    kill(1)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    assert not _rounds(tmp_path / "b")
    kill(None)
    _go(tmp_path, "b")
    assert tree(tmp_path / "b") == tree(tmp_path / "a")


def test_foreign_journal_is_refused_before_any_render(tmp_path, fake, kill):
    kill(2)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    kill(None)
    n = len(fake)
    with pytest.raises(ValueError, match="journal belongs to a different recipe"):
        _go(tmp_path, "b", RECIPE | {"seed": 4})
    assert len(fake) == n


def test_damaged_journal_images_are_refused(tmp_path, kill):
    kill(3)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    kill(None)
    victim = next((tmp_path / "b" / JOURNAL / "images").glob("*.png"))
    victim.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match its name"):
        _go(tmp_path, "b")
    victim.unlink()
    with pytest.raises(ValueError, match="missing"):
        _go(tmp_path, "b")


def test_stray_tmp_file_is_ignored(tmp_path, tree, kill):
    _go(tmp_path, "a")
    kill(3)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    (tmp_path / "b" / JOURNAL / ".round-002.json.x.tmp").write_text("{")
    kill(None)
    _go(tmp_path, "b")
    assert tree(tmp_path / "b") == tree(tmp_path / "a")


def test_journal_round_trip(tmp_path):
    header = {"recipe_sha256": "x", "schema_version": 2, "slots_planned": 1}
    png = b"not a real png"
    import hashlib

    sha = hashlib.sha256(png).hexdigest()
    row = {"image_sha256": sha}
    write_round(tmp_path, header, 0, {3: [row]}, [{"a": 1}], {sha: png}, [("c@1", "cm", None, ("flag",))], 2, 1)
    (b,) = read_journal(tmp_path, header)
    assert b["kept"] == {3: [row]} and b["images"] == {sha: png} and b["entries"] == [("c@1", "cm", None, ("flag",))]
    assert (b["no_draw"], b["not_rendered"], b["ledger"]) == (2, 1, [{"a": 1}])
    with pytest.raises(ValueError, match="different recipe"):
        read_journal(tmp_path, header | {"slots_planned": 2})
