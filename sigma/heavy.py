"""Sigma's whisper lock: one whisper at a time on this machine, among Sigma's own runs only.

SIGMA_HEAVY_LOCK overrides the path; "none" turns it off. A process that already holds it does not take it again.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

DEFAULT = Path.home() / ".local/state/sigma/whisper.lock"
CHECKOUT = Path(__file__).resolve().parent.parent.name
_held: int | None = None
_niced = False


def path() -> Path | None:
    where = os.environ.get("SIGMA_HEAVY_LOCK") or str(DEFAULT)
    return None if where == "none" else Path(where).expanduser()


def holder(lock: Path) -> str:
    try:
        pid, started, checkout, what = lock.read_text(encoding="utf-8").splitlines()[0].split("\t")
        return f"held by {what} in {checkout} (pid {pid}) for {int(time.time()) - int(started)} s"
    except (OSError, ValueError, IndexError):
        return "held by a job that wrote no holder line"


def nice() -> None:
    global _niced
    if not _niced:
        os.nice(15)
        _niced = True


def take(what: str) -> int | None:
    """Wait for the lock, write the holder line, and lower this process's priority once. Returns the descriptor that holds
    it, or None when the lock is off or already held by this process."""
    global _held
    import fcntl

    lock = path()
    if lock is None or _held is not None:
        return None
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[heavy] waiting for {lock}: {holder(lock)}", file=sys.stderr, flush=True)
        fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\t{int(time.time())}\t{CHECKOUT}\t{what}\n".encode())
    nice()
    _held = fd
    return fd


def release(fd: int | None) -> None:
    global _held
    if fd is not None:
        os.close(fd)
        _held = None


@contextlib.contextmanager
def held(what: str):
    fd = take(what)
    try:
        yield
    finally:
        release(fd)
