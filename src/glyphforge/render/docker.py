"""Sandboxed pdflatex runner.

Equations are untrusted. They are only ever written into batch.tex, never into a shell string or argv.
pdflatex runs in the pinned texlive/texlive image (by digest) with no network, a memory cap, a pid cap,
dropped capabilities, a read-only root file system, a non-root user, -no-shell-escape and a host timeout
followed by an explicit `docker kill`.

Infrastructure failures (Docker unreachable, container killed, no pdflatex log) raise
RenderInfrastructureError; only outcomes attributable to LaTeX are returned.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path

from glyphforge import resources
from glyphforge.canon.safety import render_body

# Pinned by digest, not the floating :latest tag: a silent image update would change rendering mid-project and
# make cached bitmaps incomparable to new ones. The digest is part of the cache key, so bumping it re-renders.
IMAGE_DIGEST = "sha256:0f4884ca7d287f47ab466d2dd405d4c901c576585363f628863a7ca7eea21301"
IMAGE = f"texlive/texlive@{IMAGE_DIGEST}"

# docker run errors, command not executable / not found, SIGKILL (OOM), SIGSEGV
INFRA_EXIT_CODES = frozenset({125, 126, 127, 137, 139})
# SIGKILL (OOM at the memory cap) and SIGSEGV can also be caused by one pathological equation (a degenerate repetition loop
# in a prediction). They are not raised at once: the batch is bisected, and only a singleton that is killed while a trivial
# control equation is killed too counts as an infrastructure failure.
KILL_EXIT_CODES = frozenset({137, 139})
CONTROL_LATEX = "x"
CONTROL_ENV = "\\begin{equation*}x\\end{equation*}"
KILLED_NOTE = "container killed (oom/segv)"

_PREAMBLE_BYTES = (importlib.resources.files("glyphforge.render") / "preamble.tex").read_bytes()
PREAMBLE = _PREAMBLE_BYTES.decode("utf-8")
PREAMBLE_SHA256 = hashlib.sha256(_PREAMBLE_BYTES).hexdigest()


class RenderInfrastructureError(RuntimeError):
    """Docker or the container could not produce a pdflatex verdict.

    Never cached: the caller must fix the infrastructure and rerun.
    """


def docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGE], check=False, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def docker_diagnosis() -> str:
    """Why docker_available() failed: daemon unreachable, or image not pulled yet. Never raises."""
    try:
        r = subprocess.run(["docker", "info"], check=False, capture_output=True, timeout=20)
        if r.returncode != 0:
            return "docker daemon unreachable (`docker info` failed): start Docker"
        return f"image not present locally: run `docker pull {IMAGE}`"
    except Exception:  # noqa: BLE001 - diagnosis only
        return f"docker unreachable or slow; if the daemon is up, run `docker pull {IMAGE}`"


def _batch_source(latexes: Sequence[str], *, wrapper: str = "display", preamble: str | None = None) -> str:
    parts = [PREAMBLE if preamble is None else preamble, "\\begin{document}\n"]
    for latex in latexes:
        body = render_body(latex, wrapper=wrapper)
        parts.append(body + "\n\\newpage\n")
    parts.append("\\end{document}\n")
    return "".join(parts)


def _docker_cmd(name: str, workdir: Path) -> list[str]:
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", resources.DOCKER_MEMORY, "--memory-swap", resources.DOCKER_MEMORY,
        "--cpus", "2", "--pids-limit", "512",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=256m",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", "HOME=/tmp", "-e", "TEXMFVAR=/tmp/texmf-var",
        "-v", f"{workdir}:/work", "-w", "/work",
        IMAGE,
        "pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "batch.tex",
    ]


def _first_error(log: str) -> str:
    for line in log.splitlines():
        if line.startswith("!"):
            return line[:120]
    return ""


def _infra_error(workdir: Path, what: str, proc: subprocess.CompletedProcess) -> RenderInfrastructureError:
    shutil.rmtree(workdir, ignore_errors=True)
    return RenderInfrastructureError(f"{what} (exit {proc.returncode}): {(proc.stderr or '')[:300]}")


_START_LOCK = threading.Lock()
_inflight = [0]  # containers started by this process and not yet finished (guarded by _START_LOCK)


def _run_batch(
    latexes: Sequence[str],
    work_root: Path,
    timeout_s: int,
    wrapper: str = "display",
    *,
    preamble: str | None = None,
    source: str | None = None,
) -> tuple[Path | None, str, bool]:
    """Compile one batch. Returns (workdir with batch.pdf or None, first error line, timed_out).

    Only outcomes attributable to LaTeX are returned; infrastructure failures raise RenderInfrastructureError.
    `source`, when given, is written to batch.tex verbatim instead of the wrapped equations. It is for trusted
    callers only (the doctor probe and sandbox tests); the public render path never passes it.
    """
    with _START_LOCK:
        # Serialized: the check and the reservation are one step, and containers already running are counted at their
        # full cap (conservative), so N workers cannot all pass the MemAvailable check at the same moment.
        resources.preflight(ram_gb=resources.DOCKER_MEMORY_GB, workers=_inflight[0] + 1, timeout_s=600)
        _inflight[0] += 1
    try:
        return _run_batch_reserved(latexes, work_root, timeout_s, wrapper, preamble=preamble, source=source)
    finally:
        with _START_LOCK:
            _inflight[0] -= 1


def _run_batch_reserved(
    latexes: Sequence[str],
    work_root: Path,
    timeout_s: int,
    wrapper: str = "display",
    *,
    preamble: str | None = None,
    source: str | None = None,
) -> tuple[Path | None, str, bool]:
    keep = False
    workdir: Path | None = None
    try:
        work_root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="batch-", dir=work_root))
        text = source if source is not None else _batch_source(latexes, wrapper=wrapper, preamble=preamble)
        (workdir / "batch.tex").write_text(text, encoding="utf-8")
        name = f"glyphforge-render-{uuid.uuid4().hex}"
        try:
            proc = subprocess.run(
                _docker_cmd(name, workdir.resolve()), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired:
            # equivalent of `docker kill <name>`: the host timeout is the only limit, so stop the container explicitly
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            return None, "timeout", True
        if proc.returncode in KILL_EXIT_CODES:
            return None, f"{KILLED_NOTE}, exit {proc.returncode}", False
        if proc.returncode in INFRA_EXIT_CODES:
            raise _infra_error(workdir, "docker or container failure", proc)
        log_path = workdir / "batch.log"
        if not log_path.exists():
            raise _infra_error(workdir, "no pdflatex log produced", proc)
        err = _first_error(log_path.read_text(encoding="utf-8", errors="replace"))
        if err:
            return None, err, False
        if proc.returncode != 0:
            raise _infra_error(workdir, "non-zero exit without a LaTeX error", proc)
        if not (workdir / "batch.pdf").exists():
            raise _infra_error(workdir, "no pdf produced", proc)
        keep = True
        return workdir, "", False
    except OSError as e:
        # PermissionError, disk full, docker binary vanished: the sandbox could not give a verdict
        raise RenderInfrastructureError(f"{type(e).__name__} while running a render batch: {e}") from e
    finally:
        # the workdir is only handed to the caller on success; every other path (including raw exceptions) removes it
        if workdir is not None and not keep:
            shutil.rmtree(workdir, ignore_errors=True)
