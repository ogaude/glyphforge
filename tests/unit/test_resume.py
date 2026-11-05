import json

import pytest

from glyphforge import pipeline
from glyphforge.pipeline import run
from glyphforge.store import JOURNAL, journal_image, read_journal, write_round

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


def test_chunked_rounds_are_byte_identical(tmp_path, tree, fake, monkeypatch):
    """WR-04: rendering a round in slot chunks changes no byte of the store."""
    _go(tmp_path, "a")
    monkeypatch.setattr(pipeline, "SLOTS_PER_RENDER", 1)
    n = len(fake)
    _go(tmp_path, "b")
    assert len(fake) > n + 1 and tree(tmp_path / "b") == tree(tmp_path / "a")


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


def test_journal_from_other_inputs_is_refused(tmp_path, kill):
    """WR-03: a different token counter or edited file-source content is not hidden behind the same recipe hash."""
    kill(2)
    with pytest.raises(RuntimeError, match="killed"):
        _go(tmp_path, "b")
    kill(None)
    with pytest.raises(ValueError, match="journal belongs to a different recipe"):
        run(RECIPE, tmp_path / "b", cache=tmp_path / "c-b", token_counter=len)
    src = tmp_path / "f.jsonl"
    src.write_text("".join(json.dumps({"latex": x}) + "\n" for x in RECIPE["source"]["formulas"]), "utf-8")
    recipe = RECIPE | {"source": {"kind": "file", "path": "f.jsonl", "licence": "CC0-1.0"}}
    kill(2)
    with pytest.raises(RuntimeError, match="killed"):
        run(recipe, tmp_path / "f", cache=tmp_path / "c-f", base_dir=tmp_path)
    kill(None)
    src.write_text(src.read_text("utf-8") + json.dumps({"latex": "v+d"}) + "\n", "utf-8")
    with pytest.raises(ValueError, match="journal belongs to a different recipe"):
        run(recipe, tmp_path / "f", cache=tmp_path / "c-f", base_dir=tmp_path)


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
    assert journal_image(tmp_path, png) == sha
    write_round(tmp_path, header, 0, {3: [row]}, [{"a": 1}], [("c@1", "cm", None, ("flag",))], 2, 1)
    (b,) = read_journal(tmp_path, header)
    assert b["kept"] == {3: [row]} and "images" not in b and b["entries"] == [("c@1", "cm", None, ("flag",))]
    assert (b["no_draw"], b["not_rendered"], b["ledger"]) == (2, 1, [{"a": 1}])
    with pytest.raises(ValueError, match="different recipe"):
        read_journal(tmp_path, header | {"slots_planned": 2})
