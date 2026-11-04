import re
import subprocess
import sys
from pathlib import Path

CODE = """
import sys
import glyphforge.canon as c
heavy = {"numpy", "scipy", "PIL", "pypdfium2", "typer", "yaml", "pydantic", "pyarrow"}
loaded = heavy & set(sys.modules)
assert not loaded, loaded
assert callable(c.canonicalize) and callable(c.canonical) and callable(c.tokenize)
"""


def test_canon_imports_without_heavy_deps():
    subprocess.run([sys.executable, "-I", "-c", CODE], check=True)


def test_no_glyphfix_math_import_in_src():
    rx = re.compile(r"^\s*(from|import)\s+glyphfix_math", re.MULTILINE)
    src = Path(__file__).resolve().parents[2] / "src" / "glyphforge"
    assert not [p for p in src.rglob("*.py") if rx.search(p.read_text(encoding="utf-8"))]
