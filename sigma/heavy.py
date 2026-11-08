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
GAP = 6  # must exceed Alpha's non-blocking poll interval, or Alpha never sees the lock free between Sigma holds
RELEASED = "sigma-released"
_held: int | None = None
_niced = False


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


def released_at(fd: int) -> float:
    """When a Sigma process last released the lock, from the line it left under the holder line; 0 when another job holds
    or held it since (taking it rewrites the file)."""
    for line in os.pread(fd, 4096, 0).decode(errors="replace").splitlines():
        name, _, when = line.partition("\t")
        if name == RELEASED:
            try:
                return float(when)
            except ValueError:
                return 0.0
    return 0.0


def take(what: str) -> int | None:
    """Wait for the lock, write the holder line, and lower this process's priority once. Returns the descriptor that holds
    it, or None when the lock is off or already held by this process or an ancestor lockf. Within GAP seconds of a Sigma
    release it lets go again at once and waits out the rest, so a job that polls (Alpha) gets in between Sigma's holds."""
    global _held, _niced
    import fcntl

    lock = path()
    if lock is None or _held is not None or ancestor_lockf_holds(lock):
        return None
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    said = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not said:
                print(f"[heavy] waiting for {lock}: {holder(lock)}", file=sys.stderr, flush=True)
                said = True
            fcntl.flock(fd, fcntl.LOCK_EX)
        if (left := released_at(fd) + GAP - time.time()) <= 0:
            break
        fcntl.flock(fd, fcntl.LOCK_UN)
        time.sleep(left)
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\t{int(time.time())}\t{CHECKOUT}\t{what}\n".encode())
    if not _niced:
        os.nice(15)
        _niced = True
    _held = fd
    return fd


def release(fd: int | None) -> None:
    global _held
    if fd is not None:
        os.write(fd, f"{RELEASED}\t{time.time()}\n".encode())
        os.close(fd)
        _held = None


@contextlib.contextmanager
def held(what: str):
    fd = take(what)
    try:
        yield
    finally:
        release(fd)
