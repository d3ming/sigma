"""The machine's shared heavy-job lock, compatible with `lockf -k <path>` and with Alpha's holder line.

SIGMA_HEAVY_LOCK overrides the path; "none" turns it off. A process that already holds it, or runs under a `lockf` of the
same path, does not take it again: flock on a second descriptor would wait on itself forever.
"""
from __future__ import annotations

import contextlib
import functools
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT = Path.home() / ".local/state/alpha/heavy.lock"
CHECKOUT = Path(__file__).resolve().parent.parent.name
GAP = 6  # seconds between this process's holds; Alpha polls the lock every 5 s, so a shorter gap never lets it in
_held: int | None = None
_niced = False
_released = 0.0


def path() -> Path | None:
    where = os.environ.get("SIGMA_HEAVY_LOCK") or str(DEFAULT)
    return None if where == "none" else Path(where).expanduser()


@functools.lru_cache(maxsize=None)
def ancestor_lockf_holds(lock: Path) -> bool:
    """An ancestor process is `lockf ... <lock> ...`, so the lock is already held for this process tree."""
    names = {str(lock), str(lock.resolve())}
    pid = os.getppid()
    for _ in range(40):
        if pid <= 1:
            return False
        listed = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True,
                                check=False).stdout.split()
        if len(listed) < 2:
            return False
        if Path(listed[1]).name == "lockf" and names & set(listed[2:]):
            return True
        pid = int(listed[0])
    return False


def holder(lock: Path) -> str:
    try:
        pid, started, checkout, what = lock.read_text(encoding="utf-8").splitlines()[0].split("\t")
        return f"held by {what} in {checkout} (pid {pid}) for {int(time.time()) - int(started)} s"
    except (OSError, ValueError, IndexError):
        return "held by a job that wrote no holder line"


def take(what: str) -> int | None:
    """Wait for the lock, write the holder line, and lower this process's priority once. Returns the descriptor that holds
    it, or None when the lock is off or already held by this process or an ancestor lockf."""
    global _held, _niced
    import fcntl

    lock = path()
    if lock is None or _held is not None or ancestor_lockf_holds(lock):
        return None
    lock.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(max(0.0, _released + GAP - time.monotonic()))
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[heavy] waiting for {lock}: {holder(lock)}", file=sys.stderr, flush=True)
        fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\t{int(time.time())}\t{CHECKOUT}\t{what}\n".encode())
    if not _niced:
        os.nice(15)
        _niced = True
    _held = fd
    return fd


def release(fd: int | None) -> None:
    global _held, _released
    if fd is not None:
        os.close(fd)
        _held, _released = None, time.monotonic()


@contextlib.contextmanager
def held(what: str):
    fd = take(what)
    try:
        yield
    finally:
        release(fd)
