"""Publication audit: no LightOn endorsement wording, no personal data, one git identity, consistent citations."""

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from test_card import MANIFEST, RUN

from glyphforge.export.card import NO_ENDORSE, dataset_card

ROOT = Path(__file__).resolve().parents[2]
GLOBS = (
    "README.md", "CHANGELOG.md", "CITATION.cff", "docs/**/*.md", "recipes/*.yaml", ".github/workflows/*.yml", "scripts/*.py", "scripts/*.sh",
    "src/glyphforge/export/card_template.md",
)  # fmt: skip
SURFACES = sorted({p for g in GLOBS for p in ROOT.glob(g)})
SRC = sorted(p for p in (ROOT / "src" / "glyphforge").rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".yaml", ".json", ".tex"})
LIGHTON = re.compile("lighton", re.IGNORECASE)
GMAIL = re.compile(r"[\w.+-]+@" + "gmail" + r"\.com", re.IGNORECASE)
LOCAL = (str(ROOT), str(Path.home()) + "/", "/mnt/" + "datas")
IDENTITY = "ogaude <ogaude.code@proton.me>"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def test_lighton_wording():
    assert NO_ENDORSE in _text(ROOT / "README.md")
    for path in SURFACES:
        for line in _text(path).splitlines():
            assert not LIGHTON.search(line) or NO_ENDORSE in line, f"{path.relative_to(ROOT)}: {line.strip()}"
    for repo_id in (None, "owner/name"):
        card = dataset_card(RUN, MANIFEST, repo_id)
        assert card.count(NO_ENDORSE) == 1
        assert not LIGHTON.search(card.replace(NO_ENDORSE, ""))


def test_src_names_model_only():
    for path in SRC:
        text = _text(path).replace(NO_ENDORSE, "")
        assert not re.search("lighton(?!ocr)", text, re.IGNORECASE), path.relative_to(ROOT)


def test_no_personal_data():
    for path in [*SURFACES, *SRC]:
        text = _text(path)
        assert not GMAIL.search(text) and not any(n in text for n in LOCAL), path.relative_to(ROOT)


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout")
def test_git_identity():
    # --no-merges: the synthetic merge commit GitHub creates for pull_request checkouts has its own committer
    lines = set(_git("log", "--all", "--no-merges", "--format=%an <%ae>|%cn <%ce>").splitlines())
    assert lines == {f"{IDENTITY}|{IDENTITY}"}
    assert not GMAIL.search(_git("log", "--all", "--format=%B"))


def test_citation_consistency():
    cff = yaml.safe_load(_text(ROOT / "CITATION.cff"))
    assert cff["title"] in dataset_card(RUN, MANIFEST)
    assert cff["references"][0]["title"] in _text(ROOT / "src/glyphforge/export/card.py")
    assert str(cff["version"]) == tomllib.loads(_text(ROOT / "pyproject.toml"))["project"]["version"]
