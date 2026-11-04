"""Environment diagnosis: Docker, the pinned image, font/macro availability (one sandboxed probe compile), memory, cache.

Read-only unless pull=True, which runs exactly `docker pull <pinned image>`. Stdlib + glyphforge only, so a core install
can run `python -m glyphforge.render.doctor`.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

from glyphforge import paths, resources
from glyphforge.render import docker


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str


PROBE_FILES = (
    "newtx.sty", "newtxmath.sty", "stix2.sty", "libertine.sty", "mathpazo.sty", "lmodern.sty",
    "mathrsfs.sty", "upgreek.sty", "bm.sty", "extarticle.cls", "lgrmath.sty",
)  # fmt: skip
# only Phase 2 needs \omicron from lgrmath, so its absence is reported but does not fail the probe
OPTIONAL = frozenset({"lgrmath.sty"})


def run_checks(*, pull: bool = False, cache: Path | None = None) -> list[Check]:
    checks: list[Check] = []
    try:
        info = docker.subprocess.run(["docker", "info"], check=False, capture_output=True, timeout=20)
        ok = info.returncode == 0
    except (OSError, docker.subprocess.SubprocessError):
        ok = False
    checks.append(Check("docker", ok, "reachable" if ok else docker.docker_diagnosis()))

    if pull and ok:
        docker.subprocess.run(["docker", "pull", docker.IMAGE], check=False)
    have = ok and docker.docker_available()
    checks.append(Check("image", have, docker.IMAGE if have else f"run `glyphforge doctor --pull` or `docker pull {docker.IMAGE}`"))

    root = cache or paths.cache_dir()
    g = resources.GIB
    try:
        mem = resources.mem_available_bytes()
        cap = resources.docker_parallel_cap()
        memory = Check(
            "memory",
            cap >= 1,
            f"MemAvailable {mem / g:.1f} GiB, floor {resources.RAM_FLOOR_BYTES / g:.1f} GiB, "
            f"docker memory {resources.DOCKER_MEMORY_GB} GiB, containers that fit now: {cap}",
        )
    except (OSError, resources.GuardError) as e:
        mem, cap, memory = 0, 0, Check("memory", False, f"cannot measure MemAvailable: {e}")
    if not have:
        checks.append(Check("probe", False, "skipped: docker or image unavailable"))
    elif cap < 1:
        checks.append(
            Check(
                "probe",
                False,
                f"skipped: memory below floor + one {resources.DOCKER_MEMORY_GB} GiB container "
                f"(MemAvailable {mem / g:.1f} GiB); lower GLYPHFORGE_DOCKER_MEMORY_GB",
            )
        )
    else:
        doc = docker.PREAMBLE + "".join(
            f"\\IfFileExists{{{f}}}{{\\typeout{{GF:ok:{f}}}}}{{\\typeout{{GF:missing:{f}}}}}\n" for f in PROBE_FILES
        )
        doc += (
            "\\makeatletter\\@ifundefined{mathscr}{\\typeout{GF:missing:mathscr}}{\\typeout{GF:ok:mathscr}}\\makeatother\n"
            "\\begin{document}x\\end{document}\n"
        )
        try:
            workdir, err, timed_out = docker._run_batch([], root / "work", 120, source=doc)
        except (docker.RenderInfrastructureError, resources.GuardError) as e:
            checks.append(Check("probe", False, str(e)[:300]))
        else:
            if workdir is None:
                checks.append(Check("probe", False, "probe compile timed out" if timed_out else f"probe compile failed: {err}"))
            else:
                log = (workdir / "batch.log").read_text(encoding="utf-8", errors="replace")
                shutil.rmtree(workdir, ignore_errors=True)
                seen = set(re.findall(r"GF:ok:(\S+)", log))
                missing = [f for f in (*PROBE_FILES, "mathscr") if f not in seen]
                hard = [m for m in missing if m not in OPTIONAL]
                checks.append(Check("probe", not hard, ("missing: " + ", ".join(missing)) if missing else f"{len(PROBE_FILES) + 1} items present"))

    checks.append(memory)

    try:
        with tempfile.NamedTemporaryFile(dir=root):
            pass
        checks.append(Check("cache", True, f"{root} writable"))
    except OSError as e:
        checks.append(Check("cache", False, f"{root} not writable: {e}"))
    return checks


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(prog="python -m glyphforge.render.doctor")
    ap.add_argument("--pull", action="store_true", help="docker pull the pinned image first")
    results = run_checks(pull=ap.parse_args().pull)
    for c in results:
        print(f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    sys.exit(0 if all(c.ok for c in results) else 1)
