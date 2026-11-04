"""Rasterization of batch PDFs (300 DPI grayscale, pypdfium2) and ink-crop bitmap comparison."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np

RENDER_DPI = 300
INK_THRESHOLD = 250
TOL_SHAPE_PX = 2
TOL_PIXEL_DELTA = 64
TOLERANCE_VERSION = "2"
TOL_MAX_COMPONENT_PX = 4
TOL_MAX_DIFF_PX = 24
OVERFLOW_MARGIN_PX = 5


def _ink_bbox(arr: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(arr < INK_THRESHOLD)
    if ys.size == 0:
        return None
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def ink_crop(arr: np.ndarray) -> np.ndarray | None:
    """The ink bounding box of a grayscale page, or None for a blank page."""
    box = _ink_bbox(arr)
    if box is None:
        return None
    y0, y1, x0, x1 = box
    return arr[y0:y1, x0:x1]


def ink_overflows(arr: np.ndarray) -> bool:
    """True when ink touches the page edge, so the page may have clipped the equation."""
    box = _ink_bbox(arr)
    if box is None:
        return False
    y0, y1, x0, x1 = box
    h, w = arr.shape
    m = OVERFLOW_MARGIN_PX
    return y0 < m or x0 < m or h - y1 < m or w - x1 < m


def compare_arrays(a: np.ndarray | None, b: np.ndarray | None) -> tuple[bool, bool]:
    """(identical, tolerant). Identical is exact equality; tolerant is reported separately (D-10)."""
    if a is None or b is None:
        return False, False
    if a.shape == b.shape and np.array_equal(a, b):
        return True, True
    if abs(a.shape[0] - b.shape[0]) > TOL_SHAPE_PX or abs(a.shape[1] - b.shape[1]) > TOL_SHAPE_PX:
        return False, False
    from scipy import ndimage

    pad = TOL_SHAPE_PX
    h, w = max(a.shape[0], b.shape[0]) + 2 * pad, max(a.shape[1], b.shape[1]) + 2 * pad
    pa = np.full((h, w), 255, dtype=np.uint8)
    pa[pad : pad + a.shape[0], pad : pad + a.shape[1]] = a
    pa16 = pa.astype(np.int16)
    best: np.ndarray | None = None
    best_count = -1
    for dy in range(-pad, pad + 1):
        for dx in range(-pad, pad + 1):
            pb = np.full((h, w), 255, dtype=np.uint8)
            pb[pad + dy : pad + dy + b.shape[0], pad + dx : pad + dx + b.shape[1]] = b
            mask = np.abs(pa16 - pb.astype(np.int16)) > TOL_PIXEL_DELTA
            count = int(mask.sum())
            if best is None or count < best_count:
                best, best_count = mask, count
    assert best is not None
    if best_count > TOL_MAX_DIFF_PX:
        return False, False
    labels, n = ndimage.label(best, structure=np.ones((3, 3), dtype=bool))
    largest = int(np.bincount(labels.ravel())[1:].max()) if n else 0
    return False, largest <= TOL_MAX_COMPONENT_PX


# pdfium is not thread-safe; parallel batches rasterize one at a time (the Docker compile is what runs in parallel)
_PDFIUM_LOCK = threading.Lock()


def _rasterize(workdir: Path, expected: int) -> list[np.ndarray] | None:
    with _PDFIUM_LOCK:
        return _rasterize_locked(workdir, expected)


def _rasterize_locked(workdir: Path, expected: int) -> list[np.ndarray] | None:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(str(workdir / "batch.pdf"))
    except pdfium.PdfiumError:
        return None  # an unreadable batch PDF is a group failure (bisected by the caller), not an abort
    try:
        if len(doc) != expected:
            return None
        pages = []
        for i in range(expected):
            try:
                page = doc[i]
            except pdfium.PdfiumError:
                # pdfium cannot load this page (e.g. a degenerate or oversized MediaBox): the group is unusable
                return None
            try:
                arr = np.asarray(page.render(scale=RENDER_DPI / 72, grayscale=True).to_numpy())
            except pdfium.PdfiumError:
                return None
            finally:
                page.close()
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            pages.append(np.ascontiguousarray(arr, dtype=np.uint8))
        return pages
    finally:
        doc.close()


def _bitmap_hash(arr: np.ndarray) -> str:
    h = hashlib.sha256()
    h.update(f"{arr.shape[0]}x{arr.shape[1]}:".encode())
    h.update(arr.tobytes())
    return h.hexdigest()
