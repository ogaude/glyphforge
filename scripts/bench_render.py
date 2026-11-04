"""Throughput and peak container memory of render_many under the MemAvailable floor (CPU only)."""

from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

from glyphforge import resources
from glyphforge.render import render_many


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--batch-sizes", default="100,200")
    ap.add_argument("--cache", type=Path, required=True)
    args = ap.parse_args()
    if "glyphfix_math" in str(args.cache.resolve()):
        raise SystemExit("refusing to use a glyphfix-math cache")
    fixture = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "canon_parity.jsonl"
    rows = (json.loads(line) for line in fixture.read_text().splitlines() if line.strip())
    latex = [r["latex"] for r in rows if "latex" in r][: args.n]

    for b in (int(x) for x in args.batch_sizes.split(",")):
        stop = threading.Event()
        peak = [0.0]
        low = [resources.mem_available_bytes()]

        def poll(stop: threading.Event = stop, peak: list[float] = peak, low: list[int] = low) -> None:
            # cgroup v2 memory.peak of each glyphforge-render-* container (includes page cache), polled every 0.1 s
            while not stop.is_set():
                low[0] = min(low[0], resources.mem_available_bytes())
                ids = subprocess.run(["docker", "ps", "--filter", "name=glyphforge-render-", "-q", "--no-trunc"], capture_output=True, text=True, check=False).stdout.split()
                for cid in ids:
                    try:
                        peak[0] = max(peak[0], int(Path(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope/memory.peak").read_text()) / 1048576)
                    except (OSError, ValueError):
                        continue
                stop.wait(0.1)

        t = threading.Thread(target=poll, daemon=True)
        t.start()
        t0 = time.monotonic()
        try:
            render_many(latex, batch_size=b, cache=args.cache / f"b{b}")
        finally:
            seconds = time.monotonic() - t0
            stop.set()
            t.join(timeout=30)
        print(json.dumps({
            "batch_size": b, "n": len(latex), "seconds": round(seconds, 2), "samples_per_s": round(len(latex) / seconds, 2),
            "peak_container_mem_mib": round(peak[0], 1), "min_mem_available_gib": round(low[0] / resources.GIB, 2),
            "docker_memory_gb": resources.DOCKER_MEMORY_GB, "workers": resources.docker_parallel_cap(),
        }), flush=True)


if __name__ == "__main__":
    main()
