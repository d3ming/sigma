"""Environment check: python, whisper backend, ffmpeg, yt-dlp, network, data/ and its darkroom link, disk and the pre-push hook. Fast, no model loads."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITUNES = "https://itunes.apple.com/search?term=podcast&limit=1"
MIN_FREE_GB = 5.0


def check_python():
    ok = sys.version_info >= (3, 10)
    return ("ok" if ok else "fail", f"python {sys.version.split()[0]} ({sys.executable})" + ("" if ok else "; need >= 3.10"))


def check_whisper():
    from . import whisper

    if whisper.available():
        be = whisper.backend()
        return "ok", f"backend {be} ({whisper.model_name(be)}) importable from {sys.executable}"
    return "warn", ("no whisper backend importable here; `daily` looks for another interpreter (PA_PYTHON, .venv) "
                    "and fails if none has one. Install: pip install -e '.[whisper]' (Mac: '.[whisper,mac]')")


def check_ffmpeg():
    p = shutil.which("ffmpeg")
    return ("ok", f"ffmpeg at {p}") if p else ("warn", "ffmpeg not on PATH (needed for some audio formats and yt-dlp merges)")


def check_ytdlp():
    p = shutil.which("yt-dlp")
    if p:
        return "ok", f"yt-dlp at {p}"
    from importlib.util import find_spec

    if find_spec("yt_dlp"):
        return "ok", "yt-dlp importable as a module"
    return "warn", "yt-dlp not found (only the YouTube fallback and links --ytsearch need it)"


def _get(url: str, timeout: float = 5.0) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "wire-doctor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read(256)
        return r.status


def _first_feed() -> str | None:
    try:
        from .config import load_sources

        return next(s.rss for s in load_sources(ROOT / "sources.yaml")[0] if s.rss)
    except Exception:
        return None


def _net(label: str, url: str | None):
    if not url:
        return "warn", f"{label}: no URL to test"
    try:
        return "ok", f"{label} reachable ({_get(url)})"
    except Exception as exc:
        return "fail", f"{label} unreachable: {type(exc).__name__}: {exc}"


def check_network_feed():
    return _net("RSS feed", _first_feed())


def check_network_itunes():
    return _net("itunes.apple.com", ITUNES)




def check_data_dir():
    d = ROOT / "data"
    try:
        d.mkdir(exist_ok=True)
        probe = d / f".doctor-{os.getpid()}"
        probe.write_text("x")
        probe.unlink()
        return "ok", f"{d} writable"
    except OSError as exc:
        return "fail", f"{d} not writable: {exc}"


def check_data_link():
    """data/ is meant to be a symlink into the private darkroom clone's wire/ folder (scripts/setup.sh makes it)."""
    d = ROOT / "data"
    if d.is_symlink():
        return ("ok", f"data/ -> {os.readlink(d)}") if d.exists() else ("fail", f"data/ is a broken link to {os.readlink(d)}")
    return "warn", "data/ is not a link to darkroom/wire: run scripts/setup.sh"


def check_disk():
    free = shutil.disk_usage(ROOT).free / 1e9
    return ("ok" if free >= MIN_FREE_GB else "warn", f"{free:.0f} GB free" + ("" if free >= MIN_FREE_GB else f" (< {MIN_FREE_GB:.0f} GB; whisper downloads audio)"))


def check_people():
    from .cli import people_file

    p = people_file()
    return ("ok", f"watchlist {p}") if p.exists() else ("fail", f"no watchlist at {p}")


def check_x():
    from .xdaily import doctor_check

    return doctor_check()


def check_hooks():
    """A clone without scripts/setup.sh run pushes untested code; the hook is what makes `git push` run the suite."""
    if not (ROOT / ".git").exists():
        return "ok", "not a git clone"
    try:
        out = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "ok", "git not found"
    return ("ok", "pre-push hook on") if out == ".githooks" else ("warn", "tests do not run on push: run scripts/setup.sh once")


CHECKS = [("python", check_python), ("whisper", check_whisper), ("ffmpeg", check_ffmpeg), ("yt-dlp", check_ytdlp),
          ("rss", check_network_feed), ("itunes", check_network_itunes),
          ("data", check_data_dir), ("data link", check_data_link), ("disk", check_disk), ("people", check_people), ("x", check_x), ("hooks", check_hooks)]


def run_checks(checks=None) -> list[tuple[str, str, str]]:
    """[(level, name, message)] in order; a check that raises is a fail. Checks run in parallel (network ones are slow)."""
    checks = checks if checks is not None else CHECKS

    def one(item):
        name, fn = item
        try:
            level, msg = fn()
        except Exception as exc:
            level, msg = "fail", f"check crashed: {type(exc).__name__}: {exc}"
        return level, name, msg

    with ThreadPoolExecutor(max_workers=len(checks) or 1) as ex:
        return list(ex.map(one, checks))
