"""Atomic file writes and canonical JSONL bytes, shared by the store and the snapshot builder (stdlib only)."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
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
