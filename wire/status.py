"""Read-only run inspector: which stage a run folder is in and the single next action for an agent.

`inspect_run` never writes. `record_boundaries` is the only writer (opt-in, `status --record`): it stamps
select start/end and report start/end in manifest.json through the locked `timing.mark`.
"""
from __future__ import annotations

import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DAILY_STAGES = ("fetch", "transcribe", "rank_prep", "readers", "rank_merge", "select", "links", "report", "render", "publish")
EVAL_SAMPLE = 6  # stored episodes the weekly re-scores blind to measure drift
WEEKLY_STAGES = ("fetch", "rank_prep", "readers", "rank_merge", "publish")
CUSTOM_STAGES = ("fetch", "transcribe")  # an agent-built run (`custom-run`): what comes after transcribing is the agent's call


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def is_weekly(run: Path, manifest: dict | None) -> bool:
    if (run / "ranked.json").exists():
        return True
    return (bool(manifest) and (manifest.get("days") or 0) > 3 and not (run / "selected.json").exists()
            and not (run / "scores.json").exists())


STARTING_LOG_SECONDS = 60


def _starting(run: Path) -> bool:
    """A transcribe child was just queued: transcribe.queued names a live pid, or the log was written seconds ago."""
    q = run / "transcribe.queued"
    if q.exists():
        try:
            return _pid_alive(q.read_text().strip())
        except OSError:
            return False
    log = run / "transcribe.log"
    try:
        return time.time() - log.stat().st_mtime < STARTING_LOG_SECONDS and not (run / "transcribe.lock").exists()
    except OSError:
        return False


# transcribe_skip reasons (wire.fetch.skip_reason) that a rerun fixes; news, reruns, clips and no-audio are choices, not gaps
FIXABLE_SKIPS = ("triage cap", "audio budget", "YouTube bot check", "an earlier whisper", "whisper failed")


def transcribe_state(run: Path, manifest: dict) -> dict:
    from .fetch import can_whisper

    eps = manifest.get("episodes", [])
    total = len(eps)
    done = sum(1 for e in eps if e.get("has_transcript"))
    todo = [e for e in eps if not e.get("has_transcript") and can_whisper(e) and not e.get("whisper_error")
            and not e.get("rerun") and e.get("triage", {}).get("whisper", True)]
    lock, pid = run / "transcribe.lock", None
    if lock.exists():
        pid = lock.read_text().strip()
    t = (manifest.get("timing") or {}).get("transcribe", {})
    running = bool(pid) and _pid_alive(pid)
    if running:
        state = "running"
    elif not t.get("end") and _starting(run):
        state = "starting"  # queued child alive but has not taken the lock yet
    elif t.get("end"):
        state = "finished"
    elif t.get("start") or pid:
        state = "interrupted"  # started, no end, no live process: crashed or killed
    elif not todo:
        state = "finished"  # nothing to whisper
    else:
        state = "not_started"
    errors = sum(1 for e in eps if e.get("whisper_error"))
    audio_min = round(sum(e.get("duration") or 0 for e in todo) / 60)
    fixable = [e for e in eps if (e.get("transcribe_skip") or "").startswith(FIXABLE_SKIPS)]
    return {"state": state, "pid": pid if running else None, "transcribed": done, "total": total,
            "whisper_pending": len(todo), "audio_minutes_pending": audio_min, "errors": errors, "skipped_fixable": len(fixable)}


def _check(kind: str, path: Path, run: Path):
    """(data|None, errors) using the same validators as `wire check`."""
    from . import ranked, report

    data = _json(path)
    if data is None:
        return None, [f"{path.name} is not valid JSON"]
    try:
        data = report.validate(data, kind)
    except ranked.RankedError as exc:
        return None, [str(exc)]
    return data, report.verify(kind, data, run)


def _links_missing(sel: dict) -> list[str]:
    return [e["episode_id"] for e in sel["episodes"] if not e.get("listen_url")]


def _mtime(p: Path) -> float:
    return p.stat().st_mtime


def inspect_run(run: str | Path, arg: str | None = None, weekly: bool | None = None, env: dict | None = None) -> dict:
    run = Path(run)
    arg = arg or str(run)
    env = os.environ if env is None else env
    manifest = _json(run / "manifest.json") if (run / "manifest.json").exists() else None
    custom = bool(manifest) and manifest.get("kind") == "custom"
    wk = False if custom else is_weekly(run, manifest) if weekly is None else weekly
    out = {"run": arg, "name": run.name, "kind": "custom" if custom else "weekly" if wk else "daily", "exists": run.is_dir(),
           "stages": {}, "blockers": [], "notes": []}
    st = out["stages"]
    stages = CUSTOM_STAGES if custom else WEEKLY_STAGES if wk else DAILY_STAGES
    for s in stages:
        st[s] = "pending"

    def finish(stage, kind, summary, command=None, prompt=None):
        out["stage"] = stage
        out["next"] = {k: v for k, v in {"type": kind, "summary": summary, "command": command, "prompt": prompt}.items() if v}
        return out

    if manifest is None:
        out["stages"]["fetch"] = "pending"
        name = run.name
        cmd = (f"wire fetch --days 7 --run-name {name}" if wk else
               f"wire daily --hours 48 --run-name {name}")
        return finish("fetch", "command", "No manifest.json: fetch the episodes.", cmd)
    st["fetch"] = "done"
    tm = manifest.get("timing") or {}
    errs = [f"{k} ({v['error']})" for k, v in (manifest.get("sources") or {}).items() if v.get("error")]
    if errs:
        out["notes"].append(f"{len(errs)} source error(s) in fetch: {'; '.join(errs[:5])}")
    out["episodes"] = {"total": len(manifest.get("episodes", [])),
                       "transcribed": sum(1 for e in manifest.get("episodes", []) if e.get("has_transcript"))}
    out["timing"] = {k: {kk: vv for kk, vv in tm[k].items() if kk in ("start", "end", "seconds")}
                     for k in ("fetch", "transcribe", "select", "report", "publish") if k in tm}
    if custom:
        return _custom(run, arg, manifest, out, finish)
    return (_weekly(run, arg, manifest, out, finish, env) if wk else _daily(run, arg, manifest, out, finish, env))


def restart_command(arg: str) -> str:
    """Detached restart using the interpreter `daily` pins (bare `wire` may be a shim without whisper); appends to the log."""
    try:
        from .fetch import whisper_python

        py = whisper_python()
    except SystemExit:
        py = sys.executable
    return f"nohup {shlex.quote(py)} -m wire.cli transcribe {arg} >> {arg}/transcribe.log 2>&1 &"


def _custom(run, arg, manifest, out, finish):
    """Report transcription progress only; choosing what to do with the transcripts is the agent's judgment."""
    st = out["stages"]
    tr = transcribe_state(run, manifest)
    out["transcribe"] = tr
    if note := manifest.get("note"):
        out["notes"].append(f"custom run: {note}")
    if tr["state"] in ("running", "starting"):
        st["transcribe"] = "running"
        out["blockers"].append(f"transcribe running, {tr['transcribed']}/{tr['total']} transcribed, {tr['whisper_pending']} queued, "
                               f"~{tr['audio_minutes_pending']} min of audio left")
        return finish("transcribe", "wait", f"Wait for transcribe to finish, then run status again (log: {arg}/transcribe.log).",
                      f"wire status {arg}")
    if tr["whisper_pending"]:  # also after more picks were added to a run whose transcribe already ended
        st["transcribe"] = "failed" if tr["state"] == "interrupted" else "pending"
        out["blockers"].append(f"{tr['whisper_pending']} episode(s) still to transcribe (~{tr['audio_minutes_pending']} min of audio)")
        return finish("transcribe", "command", "Transcribe the picks without a transcript (detached; resumable).", restart_command(arg))
    st["transcribe"] = "done"
    if tr["errors"]:
        out["notes"].append(f"{tr['errors']} episode(s) failed to transcribe (whisper_error); `transcribe --retry-errors` retries them")
    return finish("analyse", "agent", f"{tr['transcribed']} of {tr['total']} episodes have a transcript. What to do with them is up to "
                  f"the agent: read the episode .md files in {arg}/ and write the analysis.")


def _daily(run, arg, manifest, out, finish, env):
    st = out["stages"]
    tr = transcribe_state(run, manifest)
    out["transcribe"] = tr
    if tr["state"] == "running":
        st["transcribe"] = "running"
        out["blockers"].append(f"transcribe still running (pid {tr['pid']}), {tr['transcribed']}/{tr['total']} transcribed, "
                               f"{tr['whisper_pending']} queued, ~{tr['audio_minutes_pending']} min of audio left")
        return finish("transcribe", "wait", "Wait for transcribe to finish, then run status again (check every ~5 min; "
                      f"log: {arg}/transcribe.log).", f"wire status {arg}")
    if tr["state"] == "starting":
        st["transcribe"] = "running"
        out["blockers"].append("transcribe was just queued and has not taken its lock yet")
        return finish("transcribe", "wait", "Transcribe is starting: wait, then run status again "
                      f"(log: {arg}/transcribe.log).", f"wire status {arg}")
    if tr["state"] in ("not_started", "interrupted"):
        st["transcribe"] = "failed" if tr["state"] == "interrupted" else "pending"
        why = "was interrupted (no live process, no end recorded)" if tr["state"] == "interrupted" else "has not started"
        out["blockers"].append(f"transcribe {why}; {tr['whisper_pending']} episodes to whisper")
        return finish("transcribe", "command", f"Transcribe {why}: (re)start it detached; it is resumable.",
                      restart_command(arg))
    st["transcribe"] = "done"
    if tr["whisper_pending"]:
        out["notes"].append(f"transcribe finished with {tr['whisper_pending']} episodes still untranscribed (budget or triage)")
    if tr["errors"]:
        out["notes"].append(f"{tr['errors']} episode(s) failed to transcribe (whisper_error)")
    if tr["skipped_fixable"]:
        out["notes"].append(f"{tr['skipped_fixable']} episode(s) have no transcript for a fixable reason (see transcribe_skip in manifest.json); "
                            "they cannot be scored until `wire transcribe --top 0` runs")
    out["optional"] = {"seeds": (run / "seeds.json").exists(), "missed": (run / "missed.md").exists()}
    if out["optional"]["missed"]:
        out["notes"].append(f"{arg}/missed.md exists: fetch or whisper anything important in it before selecting")

    if (done := _score(run, arg, out, finish, "scores.json")) is not True:
        return done
    sel_p, rep_p, md_p = run / "selected.json", run / "report.json", run / "report.md"
    if not sel_p.exists():
        return finish("select", "agent", "Pick every episode scored 6 or more (at least 3 picks a day: fill with the best 5s as lower_confidence) and write selected.json, then run check.",
                      f"wire check selected {arg}/selected.json", "prompts/select.md")
    sel, errors = _check("selected", sel_p, run)
    if errors:
        out["blockers"] += errors
        return finish("select", "agent", "selected.json fails check: fix the errors listed under blockers.",
                      f"wire check selected {arg}/selected.json", "prompts/select.md")
    st["select"] = "done"
    missing = _links_missing(sel)
    if missing:
        return finish("links", "agent", f"Set youtube_url/youtube_published in selected.json for each pick only on a title-or-guest "
                      f"and date match (web search), then resolve links. {len(missing)} of {len(sel.get('episodes') or [])} picks have no listen_url.",
                      f"wire links {arg}", "prompts/report.md")
    st["links"] = "done"
    if not rep_p.exists():
        return finish("report", "agent", "Write report.json from the picks, then render it.",
                      f"wire check report {arg}/report.json", "prompts/report.md")
    _, errors = _check("report", rep_p, run)
    if errors:
        out["blockers"] += errors
        return finish("report", "agent", "report.json fails check: fix the errors listed under blockers.",
                      f"wire check report {arg}/report.json", "prompts/report.md")
    st["report"] = "done"
    if not md_p.exists() or _mtime(md_p) < _mtime(rep_p):
        return finish("render", "command", "Render report.md and export published/.",
                      f"wire report {arg}/report.json")
    st["render"] = "done"
    pub = (manifest.get("timing") or {}).get("publish", {})
    if pub.get("end"):
        st["publish"] = "done"
        return finish("done", "done", f"Finished. Report: {arg}/report.md")
    return finish("publish", "agent", f"Commit and push published/{run.name}/ to develop (it reaches the site when develop is released to main), then record it.",
                  f"wire mark publish end --run {arg}")


def _score(run, arg, out, finish, target, eval_n=0):
    """Shared by daily (target scores.json) and weekly (ranked.json): score what the library has not scored, reuse the
    rest, and re-score a blind sample when eval_n is set. Returns True when `target` exists and passes its checks."""
    st = out["stages"]
    rank = run / "rank"
    ins = sorted(rank.glob("batch-*-in.json")) if rank.is_dir() else []
    iins = sorted(rank.glob("influencer-*-in.json")) if rank.is_dir() else []  # influencer episodes: prompts/rank-influencer.md
    if not ins and not iins and not (rank / "stored.json").exists():
        return finish("rank_prep", "command", "Condense the transcripts the library has not scored and split them into "
                      "reader batches (scored episodes keep their score).",
                      f"wire rank-prep {arg}" + (f" --eval {eval_n}" if eval_n else ""))
    st["rank_prep"] = "done"
    outs = {p.name.replace("-out.json", "") for p in rank.glob("*-out.json")}
    todo = [p for p in ins + iins + ([rank / "eval-in.json"] if (rank / "eval-in.json").exists() else [])
            if p.name.replace("-in.json", "") not in outs]
    target_p = run / target
    out["readers"] = {"batches": len(ins), "done": len(ins) - len([p for p in todo if p.name.startswith("batch-")]),
                      "eval": (rank / "eval-in.json").exists()}
    inf_todo = [p for p in todo if p.name.startswith("influencer-")]
    inf_p = run / "scores-influencer.json"
    inf_wanted = bool(iins) or (rank / "influencer-stored.json").exists()
    if todo and (not target_p.exists() or inf_todo):
        names = ", ".join(p.name for p in todo)
        extra = (" eval-in.json is a blind re-score of already-scored episodes: score it the same way and save "
                 "rank/eval-out.json; it measures drift and never changes a stored score." if any(p.name == "eval-in.json" for p in todo) else "")
        return finish("readers", "agent", f"{len(todo)} reader file(s) have no output. Give each to a reader (one per file): "
                      f"{names}; save as rank/<name>-out.json.{extra}"
                      + (f" The influencer-N-in.json files ({len(inf_todo)}) follow prompts/rank-influencer.md, not rank.md." if inf_todo else ""),
                      prompt="prompts/rank.md")
    st["readers"] = "done"
    newest = max((_mtime(p) for p in [*rank.glob("*-out.json"), rank / "stored.json", rank / "influencer-stored.json"] if p.exists()), default=0)
    if not target_p.exists() or _mtime(target_p) < newest or (inf_wanted and (not inf_p.exists() or _mtime(inf_p) < newest)):
        return finish("rank_merge", "command", f"Merge the reader outputs and stored scores into {target}.", f"wire rank-merge {arg}")
    from . import ranked, report

    try:
        data = ranked.load(str(target_p))
        ranked.validate(data, ranking=target == "ranked.json")
        errors, _ = report.ranked_verify(data, run)
        if inf_wanted:
            idata = json.loads(inf_p.read_text())
            ranked.validate(idata, ranking=False)
            errors += report.ranked_verify(idata, run)[0]
    except (ranked.RankedError, OSError, ValueError, KeyError) as exc:
        errors = [str(exc)]
    if errors:
        out["blockers"] += errors[:10]
        return finish("rank_merge", "command", f"{target} fails validation: fix the reader outputs and rerun rank-merge.",
                      f"wire rank-merge {arg}")
    st["rank_merge"] = "done"
    return True


def _weekly(run, arg, manifest, out, finish, env):
    st = out["stages"]
    tr = transcribe_state(run, manifest)
    if tr["state"] in ("running", "starting"):  # scoring now would miss the episodes still in the queue
        out["transcribe"] = tr
        out["blockers"].append(f"transcribe still running, {tr['transcribed']}/{tr['total']} transcribed, "
                               f"~{tr['audio_minutes_pending']} min of audio left")
        return finish("rank_prep", "wait", f"Wait for transcribe to finish (log: {arg}/transcribe.log), then run status again.",
                      f"wire status {arg}")
    if (done := _score(run, arg, out, finish, "ranked.json", EVAL_SAMPLE)) is not True:
        return done
    ranked_p = run / "ranked.json"
    digests = sorted(run.glob("digest*.md"), key=_mtime)
    if not digests or _mtime(digests[-1]) < _mtime(ranked_p):
        return finish("publish", "command", "Render the digest and export published/.",
                      f"wire publish {arg}/ranked.json --top 15")
    st["publish"] = "done"
    return finish("done", "done", f"Finished. Digest: {arg}/{digests[-1].name}")


def record_boundaries(run: str | Path, info: dict | None = None) -> list[str]:
    """Stamp stage boundaries code can observe, once each, from file times. Returns what it recorded.

    select.start = first look after transcribe ended; select.end = selected.json passed check (file mtime);
    report.start = select end; report.end = report.md rendered (file mtime). Never overwrites a mark.
    """
    from .timing import mark

    run = Path(run)
    info = info or inspect_run(run)
    if info.get("kind") != "daily" or not (run / "manifest.json").exists():
        return []
    t = (_json(run / "manifest.json") or {}).get("timing") or {}
    iso = lambda p: datetime.fromtimestamp(_mtime(p), timezone.utc).isoformat(timespec="seconds")
    done, s = [], info["stages"]
    if s.get("transcribe") == "done" and not t.get("select", {}).get("start"):
        end_t = _mtime(run / "selected.json") if (run / "selected.json").exists() else None
        if end_t is None or end_t >= time.time():
            mark(run, "select", "start")
        else:  # selected.json already exists: start at its time so select.seconds is never negative
            mark(run, "select", "start", iso(run / "selected.json"))
        done.append("select start")
    if s.get("select") == "done" and not t.get("select", {}).get("end"):
        mark(run, "select", "end", iso(run / "selected.json"))
        done.append("select end")
        if not t.get("report", {}).get("start"):
            mark(run, "report", "start", iso(run / "selected.json"))
            done.append("report start")
    if s.get("render") == "done" and not t.get("report", {}).get("end"):
        mark(run, "report", "end", iso(run / "report.md"))
        done.append("report end")
    return done


def log_stage(info: dict) -> None:
    """Event log: one `status` line when the stage, the next action or the number of blockers differs from the run's last one.
    The agent polls this every few minutes; only a change is news. Blockers and notes are printed once and otherwise lost."""
    from . import events

    ref = {"stage": info.get("stage"), "next": (info.get("next") or {}).get("type")}
    n = {"blockers": len(info["blockers"]), "notes": len(info["notes"])}
    if (last := events.last("status", info["name"])) and last.get("ref") == ref and (last.get("n") or {}).get("blockers") == n["blockers"]:
        return
    events.emit("status", info["name"], "warn" if info["blockers"] else "ok", n=n, warn=info["blockers"], ref=ref)


def render_text(info: dict) -> str:
    lines = [f"[status] {info['run']} ({info['kind']}) stage: {info.get('stage', '?')}"]
    lines.append("  " + "  ".join(f"{k}={v}" for k, v in info["stages"].items()))
    for n in info["notes"]:
        lines.append(f"  note: {n}")
    for b in info["blockers"]:
        lines.append(f"  blocker: {b}")
    nx = info.get("next", {})
    lines.append(f"  next ({nx.get('type')}): {nx.get('summary')}")
    if nx.get("prompt"):
        lines.append(f"    follow: {nx['prompt']}")
    if nx.get("command"):
        lines.append(f"    run: {nx['command']}")
    return "\n".join(lines)
