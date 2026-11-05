import re
import zipfile
from pathlib import Path

from hatchling.builders.wheel import WheelBuilder

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = (".planning/", ".claude/", "CLAUDE.md", "SEED.md", "/data/", "__pycache__", ".pyc")
REQUIRED = (
    "glyphforge/py.typed",
    "glyphforge/export/card_template.md",
    "glyphforge/recipe/schema.json",
    "glyphforge/render/preamble.tex",
    "glyphforge/sources/seed.yaml",
)


def _build(tmp_path):
    return next(iter(WheelBuilder(str(ROOT)).build(directory=str(tmp_path), versions=["standard"])))


def test_wheel_metadata(tmp_path):
    with zipfile.ZipFile(_build(tmp_path)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        meta = zf.read(name).decode()
    for line in (
        "License-Expression: Apache-2.0",
        "License-File: LICENSE",
        "Project-URL: Source, https://github.com/ogaude/glyphforge",
        "Description-Content-Type: text/markdown",
        "Author-email: ogaude <ogaude.code@proton.me>",
    ):
        assert line in meta, line
    assert not re.search(r"[\w.+-]+@" + "gmail" + r"\.com", meta)
    assert "License ::" not in meta


def test_wheel_contents(tmp_path):
    needles = [str(ROOT).encode(), (str(Path.home()) + "/").encode(), ("/mnt/" + "datas").encode()]
    gmail = re.compile(rb"[\w.+-]+@" + b"gmail" + rb"\.com")
    with zipfile.ZipFile(_build(tmp_path)) as zf:
        names = zf.namelist()
        bad = [n for n in names if any(f in "/" + n for f in FORBIDDEN)]
        for n in names:
            data = zf.read(n)
            if any(x in data for x in needles) or gmail.search(data):
                bad.append("content: " + n)
    assert not bad, bad
    assert any(n.endswith(".dist-info/licenses/LICENSE") for n in names)
    assert set(REQUIRED) <= set(names)
