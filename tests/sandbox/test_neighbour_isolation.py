import shutil

import pytest

from glyphforge.render import docker, raster, render_many

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker.docker_available(), reason="pinned texlive image not available")]

EQS = [
    r"x \begin{openout}3=pwned.txt\end{openout}\begin{write}3{hello}\end{write}\begin{gdef}\Leak{LEAKED}\end{gdef}",
    r"y \fontdimen22\textfont2=20pt",
    r"\mathrm{\Leak} + \frac{a}{b}",
]
LEAK = [r"x \begin{gdef}\Leak{LEAKED}\end{gdef}", r"\mathrm{\Leak} + \frac{a}{b}"]
PAIRS = [
    (r"y \fontdimen22\textfont2=20pt", r"x+\frac{a}{b}"),
    (r"\globaldefs=1 \thinmuskip=40mu", r"a\,b"),
    (r"x \] \thinmuskip=40mu \[ y", r"a\,b"),
    (r"x $$ \global\thinmuskip=40mu $$ y", r"a\,b"),
]


def test_cr02_write_payload_hits_workdir_guard(tmp_path):
    with pytest.raises(docker.RenderInfrastructureError, match="pwned.txt"):
        docker._run_batch([], tmp_path / "work", 120, source=docker._batch_source(EQS))
    assert list((tmp_path / "work").glob("batch-*")) == []
    assert list(tmp_path.rglob("pwned.txt")) == []


def test_cr02_macro_leak_potent_then_blocked(tmp_path):
    workdir, err, _ = docker._run_batch([], tmp_path / "work", 120, source=docker._batch_source(LEAK))
    assert workdir is not None and not err
    shutil.rmtree(workdir)
    batch = render_many(LEAK, cache=tmp_path / "c1", batch_size=2)
    alone = render_many([LEAK[1]], cache=tmp_path / "c2")[0]
    assert [r.status for r in batch] == ["rejected", "compile-failed"]
    assert batch[1].status == alone.status and batch[1].note == alone.note
    assert alone.note.startswith("! Undefined control sequence")
    assert [r.status for r in render_many(EQS, cache=tmp_path / "c3")] == ["rejected", "rejected", "compile-failed"]
    assert list(tmp_path.rglob("pwned.txt")) == []


@pytest.mark.parametrize(("neighbour", "target"), PAIRS)
def test_neighbour_cannot_change_bitmap(tmp_path, neighbour, target):
    alone = render_many([target], cache=tmp_path / "alone")[0]
    assert alone.status == "rendered"
    workdir, _, _ = docker._run_batch([], tmp_path / "work", 120, source=docker._batch_source([neighbour, target]))
    assert workdir is not None
    try:
        pages = raster._rasterize(workdir, 2)
        assert raster._bitmap_hash(raster.ink_crop(pages[1])) != alone.bitmap_sha256
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    batch = render_many([neighbour, target], cache=tmp_path / "batch", batch_size=2)
    assert [r.status for r in batch] == ["rejected", "rendered"]
    assert batch[1].bitmap_sha256 == alone.bitmap_sha256
