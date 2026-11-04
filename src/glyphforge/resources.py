"""CPU-only resource guard: keep Docker renders and heavy jobs above the 1.5 GiB MemAvailable floor.

preflight  waits until MemAvailable >= ram_gb * max(workers, 1) GiB + 1.5 GiB floor, else raises GuardTimeout (75).
watchdog   while a job runs, MemAvailable below the floor pauses registered children (SIGSTOP), resumes them on
           recovery (SIGCONT) and terminates them when there is no recovery within grace_s (GuardAbort, 76).

Docker jobs cannot be paused by signalling the `docker run` client, so they use a `--memory` cap
(DOCKER_MEMORY) and bounded parallelism (docker_parallel_cap).

Caps are overridable with GLYPHFORGE_DOCKER_MEMORY_GB and GLYPHFORGE_MAX_WORKERS.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

GIB = 1024**3
RAM_FLOOR_BYTES = int(1.5 * GIB)
DOCKER_MEMORY_GB = int(os.environ.get("GLYPHFORGE_DOCKER_MEMORY_GB", "4"))
DOCKER_MAX_PARALLEL = int(os.environ.get("GLYPHFORGE_MAX_WORKERS", "3"))
if DOCKER_MEMORY_GB < 1:
    raise ValueError(f"GLYPHFORGE_DOCKER_MEMORY_GB must be >= 1, got {DOCKER_MEMORY_GB}")
if DOCKER_MAX_PARALLEL < 1:
    raise ValueError(f"GLYPHFORGE_MAX_WORKERS must be >= 1, got {DOCKER_MAX_PARALLEL}")
DOCKER_MEMORY = f"{DOCKER_MEMORY_GB}g"

EXIT_PREFLIGHT_TIMEOUT = 75
EXIT_WATCHDOG_KILLED = 76
EXIT_UNMEASURABLE = 78


class GuardError(RuntimeError):
    exit_code = 1


class GuardTimeout(GuardError):
    exit_code = EXIT_PREFLIGHT_TIMEOUT


class GuardAbort(GuardError):
    exit_code = EXIT_WATCHDOG_KILLED


class GuardUnmeasurable(GuardError):
    exit_code = EXIT_UNMEASURABLE


def mem_available_bytes(meminfo_path: str = "/proc/meminfo") -> int:
    with open(meminfo_path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise GuardUnmeasurable(f"MemAvailable not found in {meminfo_path}")


@dataclass
class Sampler:
    mem: Callable[[], int]


def _gib(n: float) -> str:
    return f"{n / GIB:.1f} GiB"


def preflight(
    ram_gb: float = 0.0,
    workers: int = 1,
    *,
    timeout_s: float = 600,
    poll_s: float = 10,
    sampler: Sampler | None = None,
    log: Callable[[str], object] = print,
) -> None:
    """Wait until the declared RAM need fits, else raise GuardTimeout (75).

    Needed MemAvailable = ram_gb * max(workers, 1) GiB + the 1.5 GiB floor, so a starting job never
    pushes the system under the floor.
    """
    s = sampler or Sampler(mem=mem_available_bytes)
    need = int(ram_gb * max(workers, 1) * GIB) + RAM_FLOOR_BYTES
    deadline = time.monotonic() + timeout_s
    while True:
        mem = s.mem()
        if mem >= need:
            return
        text = (
            f"short: MemAvailable {_gib(mem)} < needed {_gib(need)} "
            f"(job {ram_gb * max(workers, 1):.1f} GiB + floor {_gib(RAM_FLOOR_BYTES)})"
        )
        if time.monotonic() >= deadline:
            raise GuardTimeout(f"{text}\naborting, no work started")
        log(text)
        time.sleep(poll_s)


def docker_parallel_cap(*, sampler: Sampler | None = None, per_container_gb: float | None = None, max_parallel: int | None = None) -> int:
    """How many Docker containers fit now: min(max_parallel, floor((MemAvailable - floor) / per_container)); may be 0."""
    s = sampler or Sampler(mem=mem_available_bytes)
    per_container_gb = DOCKER_MEMORY_GB if per_container_gb is None else per_container_gb
    max_parallel = DOCKER_MAX_PARALLEL if max_parallel is None else max_parallel
    spare = s.mem() - RAM_FLOOR_BYTES
    if spare <= 0:
        return 0
    return max(0, min(max_parallel, int(spare // (per_container_gb * GIB))))


class Guard:
    def __init__(self, *, watch_s: float, grace_s: float, sampler: Sampler, log: Callable[[str], object]):
        self.paused = False
        self.aborted = False
        self._watch_s = watch_s
        self._grace_s = grace_s
        self._sampler = sampler
        self._log = log
        self._pids: list[int] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused_since = 0.0

    def register_child(self, proc_or_pid) -> None:
        pid = int(getattr(proc_or_pid, "pid", proc_or_pid))
        with self._lock:
            if pid not in self._pids:
                self._pids.append(pid)

    def check(self) -> None:
        if self.aborted:
            raise GuardAbort("watchdog terminated the job: resources stayed below the floor past the grace period")

    def wait_if_paused(self, timeout_s: float | None = None) -> None:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while self.paused and not self.aborted:
            if deadline is not None and time.monotonic() >= deadline:
                return
            time.sleep(min(self._watch_s, 0.1))

    def _signal(self, sig: int) -> None:
        with self._lock:
            pids = list(self._pids)
        for pid in pids:
            try:
                pgid = os.getpgid(pid)
                if pgid != os.getpgrp():
                    os.killpg(pgid, sig)
                else:
                    os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                continue

    def _abort(self) -> None:
        self._log("guard: no recovery within grace, terminating job")
        self.aborted = True
        self._signal(signal.SIGTERM)
        self._signal(signal.SIGCONT)
        end = time.monotonic() + 10
        while time.monotonic() < end and self._alive():
            time.sleep(0.05)
        self._signal(signal.SIGKILL)

    def _alive(self) -> bool:
        with self._lock:
            pids = list(self._pids)
        for pid in pids:
            try:
                with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                    if fh.read().rsplit(")", 1)[1].split()[0] != "Z":
                        return True
            except (OSError, IndexError):
                continue
        return False

    def _loop(self) -> None:
        while not self._stop.wait(self._watch_s):
            try:
                mem = self._sampler.mem()
            except Exception:  # noqa: BLE001, S112 - a failed sample must not kill the watchdog
                continue
            now = time.monotonic()
            if mem < RAM_FLOOR_BYTES:
                if not self.paused:
                    self.paused = True
                    self._paused_since = now
                    self._log(f"guard: pausing job: MemAvailable {_gib(mem)} below floor {_gib(RAM_FLOOR_BYTES)}")
                    self._signal(signal.SIGSTOP)
                elif now - self._paused_since > self._grace_s:
                    self._abort()
                    return
            elif self.paused:
                self._signal(signal.SIGCONT)
                self.paused = False
                self._log("guard: resources recovered, resuming job")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="guard-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)


@contextlib.contextmanager
def guard(
    ram_gb: float = 0.0,
    workers: int = 1,
    *,
    timeout_s: float = 600,
    poll_s: float = 10,
    watch_s: float = 2,
    grace_s: float = 120,
    sampler: Sampler | None = None,
) -> Iterator[Guard]:
    s = sampler or Sampler(mem=mem_available_bytes)
    preflight(ram_gb, workers, timeout_s=timeout_s, poll_s=poll_s, sampler=s)
    g = Guard(watch_s=watch_s, grace_s=grace_s, sampler=s, log=lambda m: print(m, file=sys.stderr))
    g.start()
    try:
        yield g
    finally:
        g.stop()
    g.check()
