"""Pipeline event log: one JSON line per command, step or outcome, in data/events/<Pacific date>.jsonl.

Nothing here may change what a command prints or returns: every function swallows its own errors. `data/events/` is
written only through emit(); SIGMA_EVENTS_DIR moves it (tests, proofs) and SIGMA_NO_EVENTS=1 turns the log off (conftest.py
sets it, so tests never write the real log).

A line (keys with no value are left out; `v` is VERSION):
    {"v":1,"ts":"2026-10-27T02:39:08Z","run":"2026-10-26","step":"check","status":"warn","dur_s":2.1,"n":{"warnings":4},"warn":["..."]}
`ts` is UTC; the file is named for the Pacific date. `step` is the command ("rank_merge"), a subcommand adds its name
("x_prune", "library_ingest"), or a script's own event ("launchd_daily", "maintainer"). `run` is the run folder, or the date for
`x` commands. `status` is warn when the command printed problem lines, fail on a non-zero exit or an exception. `by` is
SIGMA_BY (launchd, agent:<task>, manual). `n` holds counts a command adds with note(). `warn` holds up to MAX_WARN problem lines
(`n.warnings` is the true count), `err` the exit message or the exception's last ERR_CHARS characters.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .paths import data_root

VERSION = 1
STATUSES = ("ok", "warn", "fail", "skip", "start")
LONG = {"daily", "fetch", "transcribe"}  # also write a `start` line: a start with no end was interrupted
QUIET = {"status", "doctor", "stats", "find", "library_query", "library_stats"}  # polling and reads: logged only on failure
# A problem line as the commands print it: "[command] warning: ...", "[command] invalid: ...", "[transcribe] 12:00:00 FAILED ...".
# Anchored at the start of the line so data a command prints (a claim, a title) never marks the run as warn.
PROBLEM = re.compile(r"^\[[\w-]+\] (?:\d\d:\d\d:\d\d )?(?:warning:|invalid:|FAILED\b)")
MAX_WARN, WARN_CHARS, ERR_CHARS = 5, 200, 500
SUBCOMMANDS = {"x": "x_cmd", "library": "lib_cmd", "source": "src_cmd", "entities": "ent_cmd", "score-eval": "eval_cmd", "events": "events_cmd"}

_active: dict = {}  # the command being wrapped by run_command(): step, run, quiet, notes, tee
_ROOT = Path(__file__).resolve().parent.parent


def enabled() -> bool:
    return not os.environ.get("SIGMA_NO_EVENTS")


def events_dir() -> Path:
    return Path(os.environ.get("SIGMA_EVENTS_DIR") or data_root() / "events")


def _pacific_date(now: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo

        return now.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        return now.strftime("%Y-%m-%d")


def emit(step, run=None, status="ok", dur_s=None, n=None, warn=None, err=None, by=None, ref=None, at=None) -> None:
    """Append one event line, stamped now or `at` (a UTC datetime: harvest files a past session under its own day).
    Never raises and prints nothing."""
    try:
        if not enabled():
            return
        now = at or datetime.now(timezone.utc)
        n = dict(n or {})
        if isinstance(warn, str):
            warn = [warn]
        if warn:
            n.setdefault("warnings", len(warn))
            warn = [str(w)[:WARN_CHARS] for w in warn[:MAX_WARN]]
        by = by or os.environ.get("SIGMA_BY")
        rec = {"v": VERSION, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "run": run, "step": step, "status": status,
               "dur_s": None if dur_s is None else round(dur_s, 1), "by": by, "n": n or None, "warn": warn or None,
               "err": str(err)[:ERR_CHARS] if err else None, "ref": ref}
        line = (json.dumps({k: v for k, v in rec.items() if v is not None}, ensure_ascii=False, separators=(",", ":"),
                           default=str) + "\n").encode()
        d = events_dir()
        d.mkdir(parents=True, exist_ok=True)
        fd = os.open(d / f"{_pacific_date(now)}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)  # one locked write per line, so two processes never interleave
            while line:
                line = line[os.write(fd, line):]
        finally:
            os.close(fd)  # closing releases the lock
    except Exception:
        pass


def last(step, run=None) -> dict | None:
    """The newest event of `step` (for `run`, if given) in today's file, or None. Never raises."""
    try:
        for line in reversed((events_dir() / f"{_pacific_date(datetime.now(timezone.utc))}.jsonl").read_text().split("\n")):
            if not line.strip():
                continue  # the file ends in a newline: the last piece is empty
            rec = json.loads(line)
            if rec.get("step") == step and (run is None or rec.get("run") == run):
                return rec
    except Exception:
        pass
    return None


def note(**counts) -> None:
    """Add counts to the event the wrapped command will write when it ends. A no-op outside a wrapped command."""
    try:
        _active.get("notes", {}).update(counts)
    except Exception:
        pass


@contextlib.contextmanager
def timed(step, run=None, **kw):
    """Emit one event for the block: `ok` with its duration, or `fail` with the error (which is re-raised)."""
    t0 = time.monotonic()
    try:
        yield
    except BaseException as exc:
        emit(step, run, "fail", time.monotonic() - t0, err=f"{type(exc).__name__}: {exc}"[-ERR_CHARS:], **kw)
        raise
    emit(step, run, "ok", time.monotonic() - t0, **kw)


class _Tee:
    """Passes everything to the real stdout, and keeps the lines that report a problem. Every other attribute is the stream's."""

    def __init__(self, stream):
        self._stream, self._partial, self.lines, self.count = stream, "", [], 0

    def write(self, s):
        written = self._stream.write(s)  # first, so the output is exactly what it was
        try:
            self._scan(s)
        except Exception:
            pass
        return written

    def _scan(self, s):
        *done, self._partial = (self._partial + s).split("\n")
        self._partial = self._partial[:4096]  # one huge line (a JSON dump) must not pile up
        for line in done:
            self._keep(line)

    def _keep(self, line):
        if PROBLEM.match(line):
            self.count += 1
            if len(self.lines) < MAX_WARN:
                self.lines.append(line.strip()[:WARN_CHARS])

    def finish(self):
        if self._partial:
            self._keep(self._partial)
            self._partial = ""

    def __getattr__(self, name):
        return getattr(self._stream, name)


def describe(args) -> tuple[str, str | None, bool]:
    """(step, run, quiet) for a parsed command line."""
    cmd = args.cmd
    step = cmd.replace("-", "_")
    if sub := getattr(args, SUBCOMMANDS.get(cmd, ""), None):
        step += "_" + sub.replace("-", "_")
    where = getattr(args, "run", None) or getattr(args, "run_name", None)
    if cmd == "x":
        where = getattr(args, "date", None)
    elif cmd == "check":
        where = getattr(args, "file", None) or (args.kind if Path(args.kind).suffix else None)  # one positional is the file
    elif where is None:
        where = getattr(args, "report", None) or getattr(args, "ranked", None)
    run = None
    if isinstance(where, str) and where:
        p = Path(where)
        run = (p.parent if p.suffix else p).name or None
    return step, run, step in QUIET


def discard() -> None:
    """The command was refused before it ran: write no event for it."""
    if _active:
        _active["skip"] = True


def command(args) -> None:
    """Called by cli.main once the command line is parsed: names the event the wrapper will write."""
    try:
        if not _active or _active.get("step"):  # the outermost command names the event (`today` runs `daily` inside it)
            return
        step, run, quiet = describe(args)
        _active.update(step=step, run=run, quiet=quiet)
        if step in LONG:
            emit(step, run, "start")
    except Exception:
        pass


def run_command(fn, argv=None):
    """Run fn(argv) and log it as one event (step, run, status, duration, problem lines, error). The exit code,
    the exception and the output are the command's own."""
    tee = None
    try:
        if enabled() and not _active:
            tee = _Tee(sys.stdout)
            _active.update(t0=time.monotonic(), notes={}, tee=tee, step=None, run=None, quiet=False)
            sys.stdout = tee
    except Exception:
        tee = None
        _active.clear()
    if tee is None:
        return fn(argv)
    try:
        result = fn(argv)
    except BaseException as exc:
        _finish(argv, tee, exc=exc)
        raise
    _finish(argv, tee, result=result)
    return result


def _finish(argv, tee, exc=None, result=None) -> None:
    try:
        ctx = dict(_active)
        _active.clear()
        if sys.stdout is tee:
            sys.stdout = tee._stream
        tee.finish()
        status, err = "ok", None
        if exc is None:
            code = result
        elif isinstance(exc, SystemExit):
            code = exc.code
        else:
            code, err = 1, f"{type(exc).__name__}: {exc}"[-ERR_CHARS:]  # a traceback's reason is at the end
        if code not in (None, 0):
            status = "fail"
            if err is None:
                err = code if isinstance(code, str) else f"exit {code}"
        elif tee.lines:
            status = "warn"
        step = ctx.get("step") or next((a for a in (argv if argv is not None else sys.argv[1:]) if not a.startswith("-")), "sigma")
        if ctx.get("skip") or (ctx.get("quiet") and status != "fail"):
            return
        n = dict(ctx.get("notes") or {})
        if tee.count:
            n["warnings"] = tee.count
        emit(step, ctx.get("run"), status, time.monotonic() - ctx["t0"], n=n, warn=tee.lines, err=err)
    except Exception:
        pass


def _value(text: str):
    for kind in (int, float):
        try:
            return kind(text)
        except ValueError:
            pass
    return text


class _Quiet(Exception):
    """A bad `sigma event` argument: reported on stderr, never as an exit code."""


def event_main(argv) -> int:
    """`sigma event <step> [--run R] [--status S] [--dur SECONDS] [--n k=v ...] [--warn TEXT] [--err TEXT] [--by WHO]`: the
    entry point for shell scripts and agents. It has its own parser and always returns 0: a bad argument is printed to
    stderr and nothing is logged, so a script that logs an outcome can never fail because of the log."""
    import argparse

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise _Quiet(message)

    p = Parser(prog="sigma event", add_help=False)
    p.add_argument("step")
    p.add_argument("--run")
    p.add_argument("--status", choices=STATUSES, default="ok")
    p.add_argument("--dur", type=float)
    p.add_argument("--n", nargs="+", default=[])
    p.add_argument("--warn", action="append")
    p.add_argument("--err")
    p.add_argument("--by")
    try:
        args = p.parse_args(argv)
        n = {k: _value(v) for k, _, v in (kv.partition("=") for kv in args.n) if k}
        emit(args.step, args.run, args.status, args.dur, n=n, warn=args.warn or None, err=args.err, by=args.by)
    except (_Quiet, SystemExit, Exception) as exc:
        print(f"sigma event: ignored, nothing logged ({exc})", file=sys.stderr)
    return 0


# --- agent runs: read from the session files Claude Code already writes ------------------------------------------------

# This reads the session files Claude Code keeps on disk, a format that is Claude Code's own and not a documented interface. If it
# changes, scheduled runs are counted as "other sessions" in harvest's summary line and no agent_run lines are written. Dollars
# are not recorded: only tokens, requests and tool results.
SCHEDULED = re.compile(r'^\s*<scheduled-task name="([^"]+)"')


def sessions_dir() -> Path:
    """Where Claude Code keeps this checkout's sessions: ~/.claude/projects/<the path with every non-signalsnumeric as ->."""
    return Path(os.environ.get("SIGMA_SESSIONS_DIR") or Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(_ROOT)))


def _rows(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _text(content) -> str:
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content if isinstance(content, str) else ""


def _scheduled_name(path: Path) -> str | None:
    """The task name when the session's first user message is a scheduled task's prompt. Reads no further than that
    message, so an interactive session of hundreds of megabytes costs one line."""
    for r in _rows(path):
        if r.get("type") == "user" and (text := _text((r.get("message") or {}).get("content"))).strip():
            return m.group(1) if (m := SCHEDULED.match(text)) else None
    return None


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def summarize_session(path: Path) -> dict:
    """Tokens, requests, tool results and timing of one session file. Claude writes one line per content block of a
    response, each with the response's usage, so usage is counted once per requestId."""
    stamps, requests, tools, texts, models = [], {}, {}, {}, []
    for r in _rows(path):
        if r.get("timestamp"):
            stamps.append(_when(r["timestamp"]))
        msg = r.get("message") or {}
        if r.get("type") == "assistant":
            key = r.get("requestId") or msg.get("id") or r.get("uuid")
            use = msg.get("usage") or {}
            if key not in requests or use.get("output_tokens", 0) >= requests[key].get("output_tokens", 0):
                requests[key] = use
            texts.setdefault(key, []).append(_text(msg.get("content")))
            if msg.get("model") and msg["model"] not in models and not msg["model"].startswith("<"):
                models.append(msg["model"])
        elif r.get("type") == "user" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tools[b.get("tool_use_id")] = bool(b.get("is_error"))
    total = lambda k: sum(u.get(k, 0) or 0 for u in requests.values())
    last = " ".join(" ".join(texts[next(reversed(texts))]).split()) if texts else ""
    start, end = min(stamps), max(stamps)
    return {"start": start, "end": end, "models": models, "summary": last[:300],
            "n": {"input": total("input_tokens"), "cache_write": total("cache_creation_input_tokens"),
                  "cache_read": total("cache_read_input_tokens"), "output": total("output_tokens"), "requests": len(requests),
                  "tool_results": len(tools), "tool_errors": sum(tools.values())}}


def logged_sessions() -> set[str]:
    """Session ids that already have an agent_run line, in any day's file."""
    seen = set()
    try:
        for f in events_dir().glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8", errors="replace").split("\n"):
                if '"agent_run"' in line:
                    with contextlib.suppress(ValueError, AttributeError, KeyError, TypeError):
                        seen.add(json.loads(line)["ref"]["session"])
    except OSError:
        pass
    return seen


def harvest(directory: Path, min_age: float = 600, now: float | None = None) -> dict:
    """One agent_run event per finished scheduled-task session in `directory`, once each (idempotent by session id).
    Interactive and worker sessions are skipped, and so is a session file changed in the last `min_age` seconds, which
    is still running (a later harvest picks it up; it is never logged half done)."""
    now = time.time() if now is None else now
    done, out = logged_sessions(), {"new": [], "already": 0, "other": 0, "running": 0}
    for path in sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        if now - path.stat().st_mtime < min_age:
            out["running"] += 1
        elif not (name := _scheduled_name(path)):
            out["other"] += 1
        elif path.stem in done:
            out["already"] += 1
        else:
            s = summarize_session(path)
            emit("agent_run", None, "ok", (s["end"] - s["start"]).total_seconds(), n=s["n"], by=f"agent:{name}", at=s["end"],
                 ref={"session": path.stem, "task": name, "start": s["start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "models": s["models"], "summary": s["summary"]})
            out["new"].append((name, path.stem, s))
    return out


def events_cmd(args) -> None:
    """`sigma events harvest`."""
    if not enabled():
        sys.exit("[harvest] the event log is off (SIGMA_NO_EVENTS); nothing harvested")
    d = Path(args.dir) if args.dir else sessions_dir()
    if not d.is_dir():
        sys.exit(f"[harvest] no session folder at {d}; set SIGMA_SESSIONS_DIR or pass --dir")
    r = harvest(d, args.min_age)
    from zoneinfo import ZoneInfo

    for name, session, s in r["new"]:
        n = s["n"]
        print(f"[harvest] {name} {s['start'].astimezone(ZoneInfo('America/Los_Angeles')):%Y-%m-%d %H:%M} PT "
              f"{(s['end'] - s['start']).total_seconds():.0f} s, output {n['output']:,}, cache-read {n['cache_read'] / 1e6:.2f} M, "
              f"tool results {n['tool_results']} ({n['tool_errors']} errors), session {session[:8]}")
    note(new=len(r["new"]), already=r["already"], running=r["running"])
    print(f"[harvest] {len(r['new'])} new agent runs, {r['already']} already logged, {r['other']} other sessions, "
          f"{r['running']} still running")
