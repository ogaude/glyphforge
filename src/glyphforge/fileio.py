"""Atomic file/dir writes, file hashing and canonical JSONL bytes, shared by the store, snapshot, blocklist and export (stdlib only)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def jsonl_bytes(rows: Sequence[dict]) -> bytes:
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


@contextlib.contextmanager
def atomic_dir(out: Path) -> Iterator[Path]:
    """Yield a temp dir next to ``out`` and rename it into place on success; refuse a non-empty target."""
    if out.exists():
        if any(out.iterdir()):
            raise FileExistsError(f"{out} already exists")
        out.rmdir()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=out.parent, prefix=f".{out.name}."))
    try:
        yield tmp
        os.replace(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
