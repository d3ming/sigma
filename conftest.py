"""Repo root on sys.path (so `from tests.x import ...` works under plain `pytest`); tests never pick a real whisper backend."""
import os
import resource
import time

import pytest

SLOW = 5.0 if os.environ.get("CI") else 1.0  # GitHub runners measured 2.4-3.3x slower than the Mac the limits were set on (2026-10-26)
TEST_SECONDS = 1.0 * SLOW  # one test, CPU time incl. subprocesses; sleeps and network waits fall to the suite wall limit
SUITE_SECONDS = 5.0 * SLOW  # the whole run, on the Mac


@pytest.fixture(autouse=True)
def _whisper_env(monkeypatch, tmp_path_factory):
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)  # a git hook sets GIT_DIR to the real repo: a test's own `git` call would act on it
    monkeypatch.setenv("PA_WHISPER_BACKEND", "faster")
    monkeypatch.delenv("PA_WHISPER_MODEL", raising=False)
    monkeypatch.delenv("PA_WHISPER_THREADS", raising=False)
    monkeypatch.setenv("PA_NO_LIBRARY", "1")  # report/publish must not ingest test runs into the real data/library.sqlite
    monkeypatch.setenv("PA_NO_PUBLISHED", "1")  # ...or export them into the committed published/ folder
    monkeypatch.setenv("PA_NO_LINK_LOOKUP", "1")  # export-time YouTube/Apple/Spotify lookups are network calls: tests pass a fake resolver
    monkeypatch.setenv("PA_NO_EVENTS", "1")  # ...or write the pipeline event log in data/events (the event test points WIRE_EVENTS_DIR at a temp folder)
    monkeypatch.setenv("PA_FEED_CACHE", str(tmp_path_factory.mktemp("feed_cache")))  # never write the real data/feed_cache
    monkeypatch.setenv("WIRE_X_DIR", str(tmp_path_factory.mktemp("x_dir")))  # never read or write the real data/x (or a darkroom clone beside this repo)
    from wire import whisper

    monkeypatch.setattr(whisper, "PREFETCH", False)  # fake URLs in tests must not be downloaded in the background


def _cpu() -> float:
    """CPU seconds of this process and the subprocesses it waited for: unlike wall time, it does not grow when the Mac is busy."""
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + kids.ru_utime + kids.ru_stime


@pytest.fixture(autouse=True)
def _test_time_limit():
    start = _cpu()
    yield
    if (took := _cpu() - start) > TEST_SECONDS:
        pytest.fail(f"took {took:.2f} CPU s; the limit is {TEST_SECONDS}s per test (fake the network, subprocess or sleep)")


def pytest_sessionstart(session):
    session.wire_start = time.perf_counter()


def pytest_sessionfinish(session, exitstatus):
    took = time.perf_counter() - session.wire_start
    full_run = session.config.args in ([], [str(session.config.rootpath)], ["tests"])
    if full_run and took > SUITE_SECONDS and exitstatus == 0:
        print(f"\n[tests] suite took {took:.1f}s; the limit is {SUITE_SECONDS}s. Delete or speed up tests (see test-audit).")
        session.exitstatus = 1
