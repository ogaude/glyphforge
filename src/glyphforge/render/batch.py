"""Batched, cached, bisecting renderer: groups items by preamble key and isolates failing formulas."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from glyphforge import paths, resources
from glyphforge.canon import safety
from glyphforge.render import cache as _cache
from glyphforge.render import docker, raster
from glyphforge.render.cache import RenderResult
from glyphforge.render.style import DEFAULT_STYLE, Style


class _AbortedError(docker.RenderInfrastructureError):
    """A sibling batch already failed; never the root cause, so it must not mask the real error."""


_ERR_LOCK = threading.Lock()


def _render_group(
    items: list[tuple[str, str]],
    work_root: Path,
    timeout_s: int,
    cache: Path | None,
    *,
    abort: threading.Event | None = None,
    errors: list[BaseException] | None = None,
    wrapper: str = "display",
    preamble: str | None = None,
) -> dict[str, RenderResult]:
    """Render a group; any failure (not only RenderInfrastructureError) stops sibling threads.

    The first real exception is kept in ``errors`` so render_many can raise it instead of an "aborted" one.
    """
    try:
        return _render_group_inner(items, work_root, timeout_s, cache, abort=abort, errors=errors, wrapper=wrapper, preamble=preamble)
    except Exception as e:
        if abort is not None:
            abort.set()
        if errors is not None and not isinstance(e, _AbortedError):
            with _ERR_LOCK:
                if not errors:
                    errors.append(e)
        raise


def _render_group_inner(
    items: list[tuple[str, str]],
    work_root: Path,
    timeout_s: int,
    cache: Path | None,
    *,
    abort: threading.Event | None = None,
    errors: list[BaseException] | None = None,
    first: tuple[Path | None, str, bool] | None = None,
    wrapper: str = "display",
    preamble: str | None = None,
) -> dict[str, RenderResult]:
    """Render (key, latex) items; write cache entries. A failing group is bisected down to singletons.

    Returns the uncached (transient) results. Raises RenderInfrastructureError, never bisecting on it.
    ``first`` is an already computed _run_batch outcome for these items (used when probing both halves of a timeout).
    """
    if abort is not None and abort.is_set():
        if first is not None and first[0] is not None:
            shutil.rmtree(first[0], ignore_errors=True)
        raise _AbortedError("aborted: an earlier batch hit an infrastructure failure")
    workdir, err, timed_out = first if first is not None else docker._run_batch([latex for _, latex in items], work_root, timeout_s, wrapper, preamble=preamble)
    pages = None
    if workdir is not None:
        try:
            pages = raster._rasterize(workdir, len(items))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if pages is None:
            err = "page count mismatch or unloadable page"
    if pages is not None:
        for (key, _), arr in zip(items, pages, strict=True):
            crop = raster.ink_crop(arr)
            if crop is None:
                _cache._cache_put(cache, RenderResult(key, "blank-page", None, None))
            elif raster.ink_overflows(arr):
                _cache._cache_put(cache, RenderResult(key, "overflow", None, None, "ink touches the page edge"))
            else:
                _cache._cache_put(
                    cache, RenderResult(key, "rendered", (int(crop.shape[0]), int(crop.shape[1])), raster._bitmap_hash(crop)), crop
                )
        return {}
    if len(items) == 1:
        key = items[0][0]
        if timed_out:
            return {key: RenderResult(key, "timeout", None, None, f"timeout after {timeout_s}s")}
        if err.startswith(docker.KILLED_NOTE):
            # Pathological equation or broken sandbox? A trivial control tells them apart.
            control = docker._run_batch([docker.CONTROL_LATEX if wrapper == "display" else docker.CONTROL_ENV], work_root, timeout_s, wrapper, preamble=preamble)
            if control[0] is not None:
                shutil.rmtree(control[0], ignore_errors=True)
                # transient and never cached: it is a property of this run's resources, not of the LaTeX
                return {key: RenderResult(key, "compile-failed", None, None, err)}
            raise docker.RenderInfrastructureError(
                f"{err} on a single equation and the control equation also failed ({control[1]}): sandbox problem, not the input"
            )
        res = RenderResult(key, "compile-failed", None, None, err)
        if err.startswith("!"):
            _cache._cache_put(cache, res)
            return {}
        return {key: res}
    mid = len(items) // 2
    left_first = right_first = None
    if timed_out:
        # If both halves also time out at their first attempt the host is too slow (swap, saturated CPU): bisecting
        # further would burn ~N timeouts and report every item as failed. Stop and call it infrastructure.
        left_first = docker._run_batch([latex for _, latex in items[:mid]], work_root, timeout_s, wrapper, preamble=preamble)
        try:
            right_first = docker._run_batch([latex for _, latex in items[mid:]], work_root, timeout_s, wrapper, preamble=preamble)
        except BaseException:
            if left_first[0] is not None:
                shutil.rmtree(left_first[0], ignore_errors=True)
            raise
        if left_first[2] and right_first[2]:
            raise docker.RenderInfrastructureError(
                f"both halves of a timed-out batch of {len(items)} also timed out after {timeout_s}s: host too slow "
                "or overloaded (check swap and CPU load), refusing to score every item as a timeout"
            )
    out = _render_group_inner(items[:mid], work_root, timeout_s, cache, abort=abort, errors=errors, first=left_first, wrapper=wrapper, preamble=preamble)
    out.update(_render_group_inner(items[mid:], work_root, timeout_s, cache, abort=abort, errors=errors, first=right_first, wrapper=wrapper, preamble=preamble))
    return out


def render_many(
    latex_list: Sequence[str],
    *,
    batch_size: int = 100,
    cache: Path | None = None,
    timeout_s: int = 300,
    max_parallel: int | None = None,
    wrapper: str = "display",
    style: Style | Sequence[Style] | None = None,
) -> list[RenderResult]:
    """Render every input (aligned with the input order); cached, batched, sandboxed, failures bisected.

    wrapper="display" (default) goes through wrap(), which strips labels and re-wraps bodies in aligned/\\[ \\]. wrapper="env"
    typesets each item verbatim and accepts only a starred equation/align/gather environment (anything else is "rejected"):
    the corpus canonicalizer uses it to render the paper's own environment and compare it with the canonical label rendered
    through the default wrapper. Cache keys carry the wrapper, so bitmaps never cross wrappers.

    style=None (or a single Style) applies to every item; a sequence gives one Style per item. Items are batched per preamble
    key (font package, class size, extras), and cache keys carry a non-default style, so bitmaps never cross styles.
    """
    if wrapper not in safety.WRAPPERS:
        raise ValueError(f"unknown wrapper {wrapper!r}; expected one of {safety.WRAPPERS}")
    if style is None or isinstance(style, Style):
        styles = [style or DEFAULT_STYLE] * len(latex_list)
    elif len(style) == len(latex_list):
        styles = list(style)
    else:
        raise ValueError(f"style sequence has {len(style)} entries for {len(latex_list)} items")
    keys = [_cache.cache_key(x, wrapper=wrapper, style=s) for x, s in zip(latex_list, styles, strict=True)]
    todo: dict[str, tuple[str, Style]] = {}
    for key, latex, s in zip(keys, latex_list, styles, strict=True):
        if key in todo:
            continue
        # check_safe runs before the cache lookup, so entries written under an older, laxer filter are not served
        reason = safety.check_safe(latex)
        if reason is None and wrapper == "env" and not safety._VERBATIM_ENV_RE.match(latex.strip()):
            reason = "not a starred display env"
        cached = _cache._cache_get(cache, key)
        if reason is not None:
            status = "empty" if reason == "empty" else "rejected"
            if cached is None or cached.status != status:
                _cache._cache_put(cache, RenderResult(key, status, None, None, reason))
            continue
        if cached is not None:
            continue
        todo[key] = (latex, s)
    transient: dict[str, RenderResult] = {}
    if todo:
        # Only when something must be rendered: fully cached runs work without Docker. A missing image or a
        # hung daemon would otherwise surface as per-item timeouts and a silently bogus result file.
        if not docker.docker_available():
            raise docker.RenderInfrastructureError(f"Docker daemon or image {docker.IMAGE} is not available: {docker.docker_diagnosis()}")
        size = batch_size if batch_size < 50 else min(max(batch_size, 50), 200)
        size = max(size, 1)
        buckets: dict[str, list[tuple[str, str]]] = {}
        preambles: dict[str, str | None] = {}
        for key, (latex, s) in todo.items():
            buckets.setdefault(s.preamble_sha256, []).append((key, latex))
            preambles[s.preamble_sha256] = None if s.is_default else s.preamble
        groups = [(items[i : i + size], preambles[pk]) for pk, items in buckets.items() for i in range(0, len(items), size)]
        parallel = max_parallel if max_parallel is not None else resources.docker_parallel_cap()
        if parallel <= 0:
            resources.preflight(ram_gb=resources.DOCKER_MEMORY_GB, timeout_s=600)
            parallel = 1
        work_root = (Path(cache) if cache is not None else paths.cache_dir()) / "work"
        abort = threading.Event()
        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=max(1, min(parallel, len(groups)))) as ex:
            futs = [
                ex.submit(_render_group, g, work_root, timeout_s, cache, abort=abort, errors=errors, wrapper=wrapper, preamble=pre)
                for g, pre in groups
            ]
            for fut in futs:
                try:
                    transient.update(fut.result())
                except BaseException as exc:
                    ex.shutdown(wait=True, cancel_futures=True)
                    # prefer the first real failure over an "aborted" one raised by a sibling that started later
                    if errors and errors[0] is not exc:
                        raise errors[0] from exc
                    raise
    out = []
    for key in keys:
        res = _cache._cache_get(cache, key) or transient.get(key)
        if res is None:
            raise RuntimeError(f"render produced no result for key {key}")
        out.append(res)
    return out


@dataclass
class PairResult:
    gt_status: str
    pred_status: str
    identical: bool | None
    tolerant: bool | None


def render_equivalence(gt: Sequence[str], pred: Sequence[str], **render_kwargs) -> list[PairResult]:
    """Per-pair render comparison. identical/tolerant are None when the ground truth does not render."""
    if len(gt) != len(pred):
        raise ValueError("gt and pred must have the same length")
    cache = render_kwargs.get("cache")
    res = render_many([*gt, *pred], **render_kwargs)
    g_res, p_res = res[: len(gt)], res[len(gt) :]
    out = []
    for g, p in zip(g_res, p_res, strict=True):
        if g.status != "rendered":
            out.append(PairResult(g.status, p.status, None, None))
            continue
        identical, tolerant = _cache.compare(g, p, cache)
        out.append(PairResult(g.status, p.status, identical, tolerant))
    return out
