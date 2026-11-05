import re
import tarfile
from pathlib import Path

from hatchling.builders.sdist import SdistBuilder

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = (".planning/", ".claude/", "CLAUDE.md", "SEED.md", "/data/", "__pycache__", ".hypothesis", ".pyc")
ALLOWED_TOP = ("src/glyphforge/", "tests/", "scripts/", "pyproject.toml", "uv.lock", "PKG-INFO", ".gitignore", "README", "LICENSE")


def test_sdist_has_no_leaks(tmp_path):
    path = next(iter(SdistBuilder(str(ROOT)).build(directory=str(tmp_path), versions=["standard"])))
    needles = [str(ROOT).encode(), (str(Path.home()) + "/").encode(), ("/mnt/" + "datas").encode()]
    gmail = re.compile(rb"[\w.+-]+@" + b"gmail" + rb"\.com")
    bad, names = [], []
    with tarfile.open(path) as tf:
        for m in tf.getmembers():
            rel = m.name.split("/", 1)[1] if "/" in m.name else ""
            names.append(rel)
            if rel and (any(f in "/" + rel for f in FORBIDDEN) or not rel.startswith(ALLOWED_TOP)):
                bad.append(m.name)
            if m.isfile():
                data = tf.extractfile(m).read()
                if any(n in data for n in needles) or gmail.search(data):
                    bad.append("content: " + m.name)
    assert not bad, bad
    assert {"src/glyphforge/__init__.py", "pyproject.toml", "tests/unit/test_sdist.py"} <= set(names)
