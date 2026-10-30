"""Per-run step timing log: one JSON line per step (name, start, end, seconds), so a slow publish says where the time went.

The log is `<x dir>/steps/<Pacific date>.jsonl` (private, next to the scan), or `$SIGMA_STEPLOG`, or `--log`. It is never published.
Three ways to write it, all appending:
  sigma step run NAME -- CMD...        run CMD, record its start, end and exit code, pass the exit code on
  sigma step mark NAME start|end       for work no command wraps (the editor writing the edition, waiting for a review)
  sigma step begin --scheduled HH:MM   the run's first line: when it was due and when it really started (lateness)
`sigma step table` prints the steps, the gaps between them (time no step claims), and the slowest step.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")


def now() -> datetime:
    return datetime.now(timezone.utc)


def log_path(arg: str | None = None) -> Path:
    if arg or os.environ.get("SIGMA_STEPLOG"):
        return Path(arg or os.environ["SIGMA_STEPLOG"])
    from .xdaily import today, x_dir

    return x_dir() / "steps" / f"{today()}.jsonl"


def append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:  # one short line per write: appends stay whole across processes
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


def run_step(path: Path, name: str, cmd: list[str]) -> int:
    start = now()
    try:
        code = subprocess.call(cmd)
    except OSError as e:
        print(f"[step] {name}: {e}", file=sys.stderr)
        code = 127
    end = now()
    append(path, {"step": name, "start": _iso(start), "end": _iso(end), "seconds": round((end - start).total_seconds()),
                  "exit": code})
    return code


def mark(path: Path, name: str, event: str, note: str = "") -> dict:
    rec = {"step": name, "event": event, "at": _iso(now())}
    if note:
        rec["note"] = note
    append(path, rec)
    return rec


def begin(path: Path, scheduled: str, note: str = "") -> dict:
    """Record the run's start against its due time (HH:MM Pacific, today); `late_seconds` is how far behind it began."""
    t = now().replace(microsecond=0)  # the logged time is whole seconds, so lateness is too
    hh, mm = (int(x) for x in scheduled.split(":"))
    due = t.astimezone(PT).replace(hour=hh, minute=mm, second=0, microsecond=0)
    rec = {"step": "run-start", "event": "begin", "at": _iso(t), "scheduled": _iso(due),
           "late_seconds": round((t - due).total_seconds())}
    if note:
        rec["note"] = note
    append(path, rec)
    return rec


def load(path: Path) -> list[dict]:
    """The log's steps in start order. A start/end pair of marks becomes one step; a start with no end stays open."""
    steps, open_ = [], {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "event" not in r:
            steps.append(r)
        elif r["event"] == "begin":
            steps.append({"step": r["step"], "start": r["at"], "end": r["at"], "seconds": 0, "begin": r})
        elif r["event"] == "start":
            open_[r["step"]] = r
        elif r["event"] == "end":
            s = open_.pop(r["step"], None)
            start = s["at"] if s else r["at"]
            steps.append({"step": r["step"], "start": start, "end": r["at"],
                          "seconds": round((_parse(r["at"]) - _parse(start)).total_seconds()),
                          **({} if s else {"note": "end without a start"})})
    steps += [{"step": s["step"], "start": s["at"], "end": None, "seconds": None, "note": "still running or never ended"}
              for s in open_.values()]
    return sorted(steps, key=lambda s: s["start"])


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def fmt(sec) -> str:
    if sec is None:
        return "-"
    sec = int(sec)
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s"


def table(steps: list[dict]) -> str:
    """Step, start, end (Pacific), seconds, share of wall time; gaps no step claims; the slowest step."""
    if not steps:
        return "no steps recorded\n"
    first = _parse(steps[0]["start"])
    ends = [_parse(s["end"]) for s in steps if s.get("end")]
    wall = (max(ends) - first).total_seconds() if ends else 0
    rows, prev_end, gap_total = [], None, 0
    for s in steps:
        st = _parse(s["start"])
        if prev_end is not None and (st - prev_end).total_seconds() >= 30:
            g = round((st - prev_end).total_seconds())
            gap_total += g
            rows.append(["(gap)", prev_end.astimezone(PT).strftime("%H:%M:%S"), st.astimezone(PT).strftime("%H:%M:%S"), fmt(g),
                         f"{g / wall:.0%}" if wall else "-", "no step claims this time"])
        en = _parse(s["end"]) if s.get("end") else None
        flag = s.get("note") or ("" if s.get("exit", 0) == 0 else f"exit {s['exit']}")
        if s.get("begin"):
            flag = f"due {_parse(s['begin']['scheduled']).astimezone(PT):%H:%M}, {fmt(abs(s['begin']['late_seconds']))} " \
                   f"{'late' if s['begin']['late_seconds'] > 0 else 'early'}"
        rows.append([s["step"], st.astimezone(PT).strftime("%H:%M:%S"), en.astimezone(PT).strftime("%H:%M:%S") if en else "-",
                     fmt(s["seconds"]), f"{s['seconds'] / wall:.0%}" if wall and s["seconds"] is not None else "-", flag])
        if en and (prev_end is None or en > prev_end):
            prev_end = en
    head = ["step", "start (PT)", "end (PT)", "time", "of wall", "note"]
    w = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    line = lambda r: "  ".join(str(c).ljust(x) for c, x in zip(r, w)).rstrip()
    timed = [s for s in steps if s.get("seconds")]
    slow = max(timed, key=lambda s: s["seconds"]) if timed else None
    out = [line(head), line(["-" * x for x in w])] + [line(r) for r in rows]
    out.append(f"\nwall {fmt(wall)}; unclaimed gaps {fmt(gap_total)}" + (f"; slowest: {slow['step']} ({fmt(slow['seconds'])})" if slow else ""))
    return "\n".join(out) + "\n"


def step_cmd(args) -> int:
    path = log_path(args.log)
    if args.step_cmd == "run":
        cmd = [c for i, c in enumerate(args.command) if not (i == 0 and c == "--")]
        if not cmd:
            print("[step] run needs a command after --", file=sys.stderr)
            return 2
        return run_step(path, args.name, cmd)
    if args.step_cmd == "mark":
        print(f"[step] {args.name} {args.event} {mark(path, args.name, args.event, args.note)['at']}")
    elif args.step_cmd == "begin":
        r = begin(path, args.scheduled, args.note)
        print(f"[step] run began {r['at']}, {r['late_seconds']} s after its {args.scheduled} PT start")
    else:
        if not path.exists():
            print(f"[step] no log at {path}", file=sys.stderr)
            return 1
        steps = load(path)
        print(json.dumps(steps, indent=1) if args.json else table(steps), end="")
    return 0
