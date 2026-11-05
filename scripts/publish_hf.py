"""Stage, audit, upload and verify the Hugging Face dataset repo tree for glyphforge-equations.

Prerequisites: a built parquet export (``glyphforge export``), its store, and the recipe whose pins resolve the source files next to it.
``upload`` and ``verify`` need the ``hf`` extra and the user's stored Hugging Face login; nothing here runs unless a subcommand is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import re
import shutil
import sys
from pathlib import Path

import yaml

from glyphforge.export.card import NO_ENDORSE, attribution_text, dataset_card
from glyphforge.recipe import load_recipe

REPO_ID = "ogaude/glyphforge-equations"
ROOT = Path(__file__).resolve().parents[1]
LICENCES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0"}
GMAIL = re.compile(rb"[\w.+-]+@" + b"gmail" + rb"\.com")
NEEDLES = (str(ROOT).encode(), (str(Path.home()) + "/").encode(), ("/mnt/" + "datas").encode())
BRAND = re.compile("light" + "on", re.IGNORECASE)
TEXT = {".md", ".json", ".jsonl", ".yaml"}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _pins(recipe_path: Path) -> list[tuple[Path, str]]:
    """(path, sha256) pairs of the mutation snapshot and the blocklist pinned by the recipe, paths relative to the recipe directory."""
    r = load_recipe(recipe_path)
    stack, pins = [r.source], []
    while stack:
        s = stack.pop()
        stack.extend(s.parts)
        if s.kind == "mutation":
            pins.append((s.path, s.sha256))
    pins.append((r.export.blocklist.path, r.export.blocklist.sha256))
    return [(recipe_path.parent / p, sha) for p, sha in pins]


def _lines(path: Path, problems: list[str], rel: str) -> None:
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if BRAND.search(line) and NO_ENDORSE not in line:
            problems.append(f"{rel}:{n}: brand mention outside the no-endorsement sentence")


def stage(export_dir: Path, store_dir: Path, recipe: Path, out: Path) -> Path:
    if out.exists():
        raise SystemExit(f"{out} exists; remove it first")
    pins = _pins(recipe)
    for p, sha in pins:
        if _sha(p) != sha:
            raise SystemExit(f"{p} does not match its recipe pin")
    run = json.loads((store_dir / "run.json").read_text(encoding="utf-8"))
    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True)
    (out / "README.md").write_text(dataset_card(run, manifest, repo_id=REPO_ID), encoding="utf-8", newline="\n")
    for name in ("ATTRIBUTION.md", "export_manifest.json"):
        shutil.copy2(export_dir / name, out / name)
    for name in ("data", "assets"):
        shutil.copytree(export_dir / name, out / name)
    (out / "source").mkdir()
    for p, _ in pins:
        for f in (p, p.with_suffix(".meta.json")):
            shutil.copy2(f, out / "source" / f.name)
    rows = [json.loads(line) for line in (out / "source" / pins[0][0].name).read_text(encoding="utf-8").splitlines() if line]
    (out / "source" / "SNAPSHOT-ATTRIBUTION.md").write_text(attribution_text(rows, derived=False), encoding="utf-8", newline="\n")
    return out


def audit(stage_dir: Path, recipe: Path | None = None) -> list[str]:
    problems: list[str] = []
    for f in sorted(p for p in stage_dir.rglob("*") if p.is_file()):
        rel = str(f.relative_to(stage_dir))
        if f.stat().st_size:
            with f.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as m:
                if GMAIL.search(m) or any(m.find(n) >= 0 for n in NEEDLES):
                    problems.append(f"{rel}: personal address or local path")
        if f.suffix in TEXT:
            _lines(f, problems, rel)
    manifest = json.loads((stage_dir / "export_manifest.json").read_text(encoding="utf-8"))
    head = yaml.safe_load((stage_dir / "README.md").read_text(encoding="utf-8").split("---\n")[1])
    if sorted(head["license"]) != sorted(k.lower() for k in manifest["licenses"]):
        problems.append(f"README licence ids {head['license']} differ from manifest licences {sorted(manifest['licenses'])}")
    pins = {p.name: sha for p, sha in _pins(recipe)} if recipe else {}
    pins.setdefault(Path(manifest["blocklist"]["path"]).name, manifest["blocklist"]["sha256"])
    for name, sha in pins.items():
        if not (stage_dir / "source" / name).is_file() or _sha(stage_dir / "source" / name) != sha:
            problems.append(f"source/{name} missing or differs from its pin")
    return problems


def upload(stage_dir: Path, repo_id: str, patterns: list[str] | None = None) -> int:
    if problems := audit(stage_dir):
        print("\n".join(problems), file=sys.stderr)
        return 1
    from huggingface_hub import HfApi

    manifest = json.loads((stage_dir / "export_manifest.json").read_text(encoding="utf-8"))
    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(
        folder_path=str(stage_dir), repo_id=repo_id, repo_type="dataset", allow_patterns=patterns or None,
        commit_message=f"glyphforge-equations {manifest['generator_version']} (recipe {manifest['recipe_sha256'][:12]})",
    )  # fmt: skip
    return 0


def verify(repo_id: str, anonymous: bool = False) -> list[str]:
    from datasets import load_dataset
    from huggingface_hub import HfApi, hf_hub_download

    token = False if anonymous else None
    ds = load_dataset(repo_id, split="train", token=token)
    problems = []
    manifest = json.loads(
        Path(hf_hub_download(repo_id, "export_manifest.json", repo_type="dataset", token=token)).read_text(encoding="utf-8")
    )
    if len(ds) != manifest["n_rows"]:
        problems.append(f"{len(ds)} rows on the Hub, manifest says {manifest['n_rows']}")
    if bad := set(ds["license"]) - LICENCES:
        problems.append(f"unexpected licences {sorted(bad)}")
    if any(lic.startswith("CC-BY") and not att for lic, att in zip(ds["license"], ds["attribution"], strict=True)):
        problems.append("CC BY row without attribution")
    ds[0]["image"].load()
    files = HfApi().list_repo_files(repo_id, repo_type="dataset", token=token)
    problems += [f"no {d}/ files on the Hub" for d in ("source", "assets") if not any(f.startswith(d + "/") for f in files)]
    card = Path(hf_hub_download(repo_id, "README.md", repo_type="dataset", token=token))
    _lines(card, problems, "README.md")
    if GMAIL.search(card.read_bytes()) or any(n in card.read_bytes() for n in NEEDLES):
        problems.append("README.md: personal address or local path")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--export", type=Path, required=True)
    s.add_argument("--store", type=Path, required=True)
    s.add_argument("--recipe", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("audit")
    a.add_argument("stage", type=Path)
    a.add_argument("--recipe", type=Path)
    u = sub.add_parser("upload")
    u.add_argument("stage", type=Path)
    u.add_argument("--repo", required=True)
    u.add_argument("--only", nargs="+")
    v = sub.add_parser("verify")
    v.add_argument("--repo", required=True)
    v.add_argument("--anonymous", action="store_true")
    args = ap.parse_args()
    match args.cmd:
        case "stage":
            print(f"staged {stage(args.export, args.store, args.recipe, args.out)}")
            problems = audit(args.out, args.recipe)
        case "audit":
            problems = audit(args.stage, args.recipe)
        case "upload":
            return upload(args.stage, args.repo, args.only)
        case _:
            problems = verify(args.repo, args.anonymous)
    print("\n".join(problems) if problems else f"{args.cmd}: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
