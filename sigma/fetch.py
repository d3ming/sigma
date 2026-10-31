from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import events
from .config import load_sources
from .ingest import Episode, discover
from .people import apply_source_tiers, discover_people, load_people
from .ingest import counterparts, different_youtube_videos, in_window, is_rerun, video_id
from .manifest import update as update_manifest
from .transcribe import MIN_TRANSCRIPT_CHARS, fmt_ts, get_transcript, is_fallback, title_match, transcript_chars
from .triage import DEFAULT_TOP
from .whisper import Budget

DEFAULT_AUDIO_MINUTES = 3600


def slug(text: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n].rstrip("-")


def same_episode(ep, known) -> bool:
    if ep.id == known.id:
        return True
    if different_youtube_videos(ep.id, known.id, video_id(ep), video_id(known)):
        return False
    if counterparts(ep, known):
        return True
    if ep.id.startswith("yt:") != known.id.startswith("yt:"):
        return False
    numbers = re.findall(r"\d+(?:[.,]\d+)*", ep.title)
    old_numbers = re.findall(r"\d+(?:[.,]\d+)*", known.title)
    if numbers != old_numbers:
        return False
    if ep.url and getattr(known, "url", None) and ep.url == known.url:
        return True
    if title_match(known.title, ep.title) < 0.8:
        return False
    known_published = getattr(known, "published_at", None)
    if isinstance(known_published, datetime):
        old_day = known_published.date().isoformat()
    else:
        old_day = str(known_published or "")[:10]
    same_day = old_day == ep.published_at.date().isoformat()
    same_show = (getattr(known, "source_id", None) == ep.source_id
                 or getattr(known, "source_name", None) == ep.source_name)
    return same_day and same_show and numbers == old_numbers


def episode_md(ep, segs: list[dict] | None, tsrc: str | None) -> str:
    front = {"episode_id": ep.id, "title": ep.title, "source": ep.source_name, "source_id": ep.source_id,
             "tier": ep.tier, "style": ep.style, "published": ep.published_at.isoformat(), "url": ep.url,
             "youtube_id": ep.youtube_id, "transcript_source": tsrc or "none"}
    body = ["---", yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip(), "---", "", f"# {ep.title}", ""]
    if ep.description:
        body += ["## Description", "", re.sub(r"<[^>]+>", " ", ep.description).strip(), ""]
    body += ["## Transcript", ""]
    if not segs:
        body.append("_No transcript found._")
    for s in segs or []:
        who = f"{s['speaker']}: " if s.get("speaker") else ""
        body.append(f"[{fmt_ts(s['start'])}] {who}{s['text']}")
    return "\n".join(body) + "\n"


def write_episode(run_dir: Path, ep: Episode, segs, tsrc, min_chars: int = MIN_TRANSCRIPT_CHARS) -> dict:
    fallback = is_fallback(segs, min_chars)
    identity = hashlib.sha256(ep.id.encode()).hexdigest()[:10]
    name = f"{ep.published_at.date()}-{slug(ep.source_id, 40)}-{slug(ep.title)}-{identity}.md"
    (run_dir / name).write_text(episode_md(ep, segs, tsrc))
    print(f"[episode] {ep.source_id}: transcript={tsrc or 'none'}")
    return {"episode_id": ep.id, "file": name, "title": ep.title, "source": ep.source_name, "source_tag": ep.source_id,
            "via": ep.via or "channel", "tier": ep.tier, "style": ep.style, "published": ep.published_at.isoformat(), "url": ep.url,
            "transcript_source": "fallback" if fallback else tsrc, "has_transcript": bool(segs) and not fallback,
            "fallback_text": fallback, "fallback_from": tsrc if fallback else None, "transcript_chars": transcript_chars(segs),
            "transcript_minutes": round(segs[-1]["start"] / 60) if segs and not fallback else 0, "audio_url": ep.audio_url,
            "youtube_id": ep.youtube_id, "transcript_url": ep.transcript_url, "rerun": is_rerun(ep.title, ep.description), "duration": ep.duration,
            **({"image_url": ep.image_url} if ep.image_url else {}),
            **({"show_image_url": ep.show_image_url} if ep.show_image_url else {}),
            "description": re.sub(r"<[^>]+>", " ", ep.description or "")[:1500]}


def load_manifest(run_dir: Path, now: datetime, days) -> dict:
    p = run_dir / "manifest.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"run_at": now.isoformat(timespec="seconds"), "days": days, "episodes": [], "skipped_seen": []}


FAILED = "lookup-failed"
YT_COOLDOWN = float(os.environ.get("SIGMA_YT_COOLDOWN", "1200"))  # seconds; a YouTube bot check has cleared within ~20 min


def safe_transcript(ep, budget):
    """One episode's lookup must never abort the whole fetch (timeouts, yt-dlp missing, blocked IP): record none and go on."""
    try:
        return get_transcript(ep, budget)
    except Exception as exc:
        print(f"[transcript] {ep.id}: {type(exc).__name__}: {str(exc)[:80]}")
        return None, FAILED


def fetch(args) -> Path:
    now = datetime.now(timezone.utc)
    from .store import Store

    sources, t3_cap = load_sources(args.sources)
    if args.only:
        sources = [s for s in sources if s.id in args.only.split(",")]
    store = Store(args.db)
    run_dir = Path(args.runs) / (args.run_name or now.strftime("%Y-%m-%d"))
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = run_dir / "transcribe.lock"
    if lock.exists() and pid_alive(pid := lock.read_text().strip()):
        raise SystemExit(f"[fetch] {lock} held by running transcribe pid {pid}; wait for it to finish, then rerun")
    path = run_dir / "manifest.json"
    prior = json.loads(path.read_text()) if path.exists() else None
    have = {e["episode_id"] for e in (prior or {}).get("episodes", [])}
    if prior:
        print(f"[run] {run_dir} exists ({len(have)} episodes); adding only new ones")
    manifest = {"run_at": now.isoformat(timespec="seconds"), "days": args.days, "episodes": [], "skipped_seen": []}
    from .timing import apply as timing_apply

    timing_apply(manifest, "fetch", "start", now.isoformat(timespec="seconds"))
    known = store.known_since(now - timedelta(days=args.days + 7))
    people_first = getattr(args, "people_first", False)
    health = {}
    person_eps, eps = [], [] if people_first else discover(sources, now, args.days, t3_cap, per_source=args.per_source,
                                                           health=health)
    if args.people:
        person_eps, manifest["people"] = discover_people(load_people(args.people), now, args.days, eps + known, args.per_person)
        apply_source_tiers(person_eps, load_sources(args.sources)[0])
    if people_first:
        eps = [e for e in discover(sources, now, args.days, t3_cap, per_source=args.per_source, health=health)
               if not any(same_episode(p, e) for p in person_eps)]
    eps += person_eps
    manifest["sources"] = health
    manifest["excluded"] = []
    keep_reruns = getattr(args, "include_reruns", False)
    for e in list(eps):
        why = "outside window" if not in_window(e.published_at, now, args.days) else (
            "rerun" if is_rerun(e.title, e.description) and not keep_reruns else None)
        if why:
            eps.remove(e)
            manifest["excluded"].append({"episode_id": e.id, "title": e.title, "published": e.published_at.isoformat(), "why": why})
            print(f"[window] skip {why}: {e.title[:60]}")
    budget = Budget(args.whisper_minutes or 0, args.whisper_per_episode)
    news_ids = {s.id for s in sources if s.news}
    eps.sort(key=lambda e: (e.source_id.startswith("person:") != people_first, e.tier, -e.published_at.timestamp()))
    todo, queued = [], set()
    for ep in eps:
        if ep.id in have:
            continue
        if getattr(args, "youtube_mirror", False) and "youtube_mirror" not in (ep.methods or []):
            ep.methods = [m for m in (ep.methods or ["podcast_transcript", "whisper"]) if m != "whisper"] + \
                ["youtube_mirror", "whisper"]
        dup = not args.refetch and (ep.id in queued or any(same_episode(ep, k) for k in todo) or store.seen(ep.id)
                                    or any(same_episode(ep, k) for k in known))
        if dup:
            manifest["skipped_seen"].append(ep.id)
            print(f"[dedupe] skip {ep.id}")
            continue
        queued.add(ep.id)
        todo.append(ep)
    # Transcript lookups are network-bound and independent, so run them side by side. Whisper is CPU-bound and shares the
    # budget, so a run that may whisper stays sequential.
    workers = 1 if args.whisper_minutes else min(4, max(1, len(todo)))
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda ep: safe_transcript(ep, budget), todo))
    for ep, (segs, tsrc) in zip(todo, results):
        failed = tsrc == FAILED  # keep the row (it can still be whispered) but leave the dedupe DB alone so a later run retries
        row = write_episode(run_dir, ep, segs, None if failed else tsrc, getattr(args, "min_transcript_chars", MIN_TRANSCRIPT_CHARS))
        row["news"] = ep.source_id in news_ids
        manifest["episodes"].append(row)
        if not failed:
            store.add_episode(ep, tsrc)
    manifest["whisper_minutes"] = round(budget.used / 60, 1)
    timing_apply(manifest, "fetch", "end")
    new = manifest

    def apply(m):
        if m is new:
            return
        ids = {e["episode_id"] for e in m.setdefault("episodes", [])}
        m["episodes"] += [r for r in new["episodes"] if r["episode_id"] not in ids]
        ids |= {r["episode_id"] for r in new["episodes"]}
        seen = set(m.setdefault("skipped_seen", []))
        m["skipped_seen"] += [i for i in dict.fromkeys(new["skipped_seen"]) if i not in seen and i not in ids]
        gone = {x["episode_id"] for x in m.setdefault("excluded", [])}
        m["excluded"] += [x for x in new["excluded"] if x["episode_id"] not in gone and x["episode_id"] not in ids]
        m["whisper_minutes"] = round(m.get("whisper_minutes", 0) + budget.used / 60, 1)
        m["sources"] = new["sources"]
        if "people" in new:
            m["people"] = new["people"]
        if not (m.get("timing", {}).get("fetch") or {}).get("end"):
            timing_apply(m, "fetch", "start", new["timing"]["fetch"]["start"])
            timing_apply(m, "fetch", "end", new["timing"]["fetch"]["end"])

    final = update_manifest(path, apply, lambda: new)
    print(f"[run] {run_dir} ({len(final['episodes'])} episodes, +{len(new['episodes'])} new)")
    events.note(episodes=len(final["episodes"]), new=len(new["episodes"]), skipped_seen=len(new["skipped_seen"]))
    return run_dir


def error_text(exc: Exception) -> str:
    """'Type: message' for the failure record: the first 200 and last 300 characters of a long message (a command line
    runs long and its reason comes last), then the tail of a failed subprocess's stderr, which holds the real reason."""
    msg = str(exc)
    if len(msg) > 500:
        msg = f"{msg[:200]} ... {msg[-300:]}"
    err = getattr(exc, "stderr", None)
    err = err.decode(errors="replace") if isinstance(err, bytes) else err
    return f"{type(exc).__name__}: {msg}" + (f" | stderr: {err.strip()[-300:]}" if err and err.strip() else "")


def episode_event(run_dir: Path, e: dict, ok: bool, wall: float, used: float, budget, tsrc: str | None, rec: dict | None) -> None:
    """One event line for an episode the transcribe loop is done with: `ok` with a transcript, `fail` without."""
    events.emit("transcribe_episode", run_dir.name, "ok" if ok else "fail", wall,
                n={"minutes": round(used / 60, 1), "budget_used": round(budget.used / 60, 1),
                   **({"attempts": rec["attempts"]} if rec else {})},
                err=None if ok else str((rec or {}).get("error") or e.get("whisper_error") or "")[-events.ERR_CHARS:],  # the reason is last
                ref={"episode": e["episode_id"], **({"source": tsrc} if tsrc else {})})


def record_failure(run_dir: Path, manifest: dict, e: dict, exc: Exception) -> dict:
    """Append to manifest['failures'] and transcribe.failed.log (one JSON line per failure)."""
    from .timing import now_iso
    from .whisper import DownloadError

    rec = {"at": now_iso(), "episode_id": e["episode_id"], "title": e.get("title", "")[:120], "stage": "transcribe",
           "error": str(exc) if isinstance(exc, DownloadError) else error_text(exc),
           "attempts": getattr(exc, "attempts", 1), "errors": getattr(exc, "errors", [type(exc).__name__]),
           "transient": getattr(exc, "transient", None)}
    manifest.setdefault("failures", []).append(rec)
    with open(run_dir / "transcribe.failed.log", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log(f"FAILED {e['episode_id']} after {rec['attempts']} attempt(s): {rec['error']}")
    return rec


def skip_reason(e: dict, *, top: int, skip_news: bool, reruns: bool, retry: bool, tried: set, yt_left: set, budget) -> str | None:
    """Why an episode has no transcript after a transcribe run, in words the status page and the selector can show.
    None when it has one. Every episode without a transcript gets a reason: an unexplained gap looks like a bug."""
    if e.get("has_transcript"):
        return None
    tri, why = e.get("triage") or {}, (e.get("triage") or {}).get("reasons") or []
    if e.get("rerun") and not reruns:
        return "rerun of an earlier episode; not whispered (--include-reruns)"
    if skip_news and is_news(e):
        return "news or market-recap show; not whispered (--news)"
    if not can_whisper(e):
        return "no audio or YouTube source to transcribe"
    clip = next((r for r in why if r.startswith("clip of")), None)
    if clip or any(r.startswith("off-domain") for r in why):
        return f"not whispered: {clip or 'off-domain namesake'}"
    if e.get("whisper_error") and e["episode_id"] not in tried and not retry:
        return f"an earlier whisper attempt failed ({e['whisper_error']}); not retried (--retry-errors)"
    if e.get("whisper_error"):
        return f"whisper failed: {e['whisper_error']}"
    if top and tri.get("whisper") is False:
        return f"triage cap: rank {tri.get('rank')} (score {tri.get('score')}) is below the top {top}; rerun with a larger --top"
    if e["episode_id"] in yt_left:
        return "YouTube bot check; left for the next transcribe run"
    if e["episode_id"] not in tried:
        return f"audio budget used up ({round(budget.used / 60)} of {round((budget.used + budget.left) / 60)} min); left for the next transcribe run"
    return "not transcribed"


def transcribe_run(args) -> Path:
    from .store import Store
    from . import whisper

    run_dir = Path(args.run)
    path = run_dir / "manifest.json"
    budget, store = Budget(args.minutes, args.per_episode), Store(args.db) if args.db else None
    retry, reruns = getattr(args, "retry_errors", False), getattr(args, "include_reruns", False)
    min_chars, tried = getattr(args, "min_transcript_chars", MIN_TRANSCRIPT_CHARS), set()
    custom = path.exists() and json.loads(path.read_text()).get("kind") == "custom"  # every pick is wanted: no triage
    if not whisper.available():
        raise SystemExit(f"[transcribe] neither mlx_whisper nor faster_whisper is importable from {sys.executable}; "
                         "run with the venv that has one (.venv/bin/sigma) or set SIGMA_PYTHON")
    # News and market-recap shows are not whispered unless asked (--news): select.md rejects them, so their audio is
    # mostly wasted GPU time. A free transcript is still kept, and a custom run's picks are always wanted.
    skip_news = not custom and not getattr(args, "news", False)
    lock = run_dir / "transcribe.lock"
    if lock.exists() and not args.force:
        pid = lock.read_text().strip()
        if pid_alive(pid):
            raise SystemExit(f"[transcribe] {lock} held by running pid {pid} (use --force)")
        log(f"stale lock from dead pid {pid or '?'}; taking over")
    lock.write_text(str(os.getpid()))
    reuse = ReuseIndex(run_dir.parent, exclude=run_dir)
    from .timing import apply as timing_apply

    top = 0 if custom else getattr(args, "top", 0) or 0
    def start(m):
        timing_apply(refresh_flags(m, run_dir, min_chars), "transcribe", "start")
        if top and ("triage" not in m or getattr(args, "retriage", False)):
            from .triage import triage

            people = load_people(args.people) if getattr(args, "people", None) and Path(args.people).exists() else []
            floor = not getattr(args, "no_tier1_floor", False)
            picked = triage(m, people, top, is_news=is_news, run_dir=run_dir, tier1_floor=floor)
            log(f"triage: whisper {len(picked)} of {m['triage']['candidates']} (top {top} + core people{' + tier-1 floor' if floor else ''})")

    prefetched: dict[str, whisper.Prefetch] = {}  # one episode ahead: audio downloads while the current one transcribes
    # A YouTube bot check holds YouTube-only episodes back until the podcast audio is done and YT_COOLDOWN has passed,
    # then retries them once. A second check leaves them untried for the next transcribe run.
    yt_blocked, yt_waited, done_ok, done_fail = None, False, 0, 0
    log(f"backend {whisper.backend()} model {whisper.model_name()}")
    try:
        update_manifest(path, start)
        while True:
            manifest = json.loads(path.read_text())  # re-read every pass: picks that `custom-run` adds while this runs are taken up
            todo = [e for e in manifest["episodes"] if not e["has_transcript"] and can_whisper(e)
                    and e["episode_id"] not in tried and (retry or not e.get("whisper_error"))
                    and not (e.get("rerun") and not reruns) and not (skip_news and is_news(e))
                    and (not top or e.get("triage", {}).get("whisper", True))]
            todo.sort(key=lambda e: (is_news(e), -e.get("triage", {}).get("score", 0),
                                     not e.get("source_tag", "").startswith("person:"), e["episode_id"]))
            if yt_blocked is not None:
                yt_left, todo = [x for x in todo if not x.get("audio_url")], [x for x in todo if x.get("audio_url")]
                if yt_left and not todo and not yt_waited and budget.take() >= 60:
                    wait = yt_blocked + YT_COOLDOWN - time.monotonic()
                    log(f"YouTube bot check: waiting {max(0, round(wait / 60))} min, then retrying {len(yt_left)} YouTube episode(s) once")
                    if wait > 0:
                        time.sleep(wait)
                    yt_blocked, yt_waited, todo = None, True, yt_left
                elif yt_left and not todo:
                    log(f"YouTube still asks for a bot check; {len(yt_left)} YouTube episode(s) left for the next transcribe run")
            if not todo or budget.take() < 60:
                break
            e = todo[0]
            before, fails, rec, t_ep = dict(e), {}, None, time.monotonic()
            tried.add(e["episode_id"])
            e.pop("whisper_error", None)
            log(f"start {e['episode_id']} ({len(todo)} left, {round(budget.left / 60)} min budget) {e['title'][:60]}")
            hit = reuse.find(e)
            pf = prefetched.pop(e["episode_id"], None)
            if whisper.PREFETCH and len(todo) > 1 and todo[1].get("audio_url") and todo[1]["episode_id"] not in prefetched \
                    and budget.left >= 120 and not reuse.find(todo[1]):
                nxt = todo[1]
                prefetched[nxt["episode_id"]] = whisper.Prefetch(nxt["audio_url"])
            try:
                if hit:
                    segs, tsrc, used = hit[0], hit[1], 0.0
                    log(f"reuse {e['episode_id']} from {hit[2]}")
                    if pf:
                        pf.cleanup()
                    if hit[3]:
                        e["transcript_url"] = hit[3]
                else:
                    t0 = time.monotonic()
                    if e.get("audio_url"):
                        segs, used = whisper.transcribe_prefetched(pf, budget) if pf else whisper.transcribe(e["audio_url"], budget)
                        tsrc = whisper.label(used)
                    else:  # YouTube-only: same label get_transcript's youtube_audio path writes
                        segs, used = whisper.transcribe_youtube(e["youtube_id"], budget)
                        tsrc = whisper.label(used, ", youtube audio")
                    log(f"whispered {round(used / 60)} audio min in {round(time.monotonic() - t0)} s wall")
            except whisper.YouTubeBlocked:
                yt_blocked = time.monotonic()
                events.emit("transcribe_episode", run_dir.name, "skip", time.monotonic() - t_ep, err="YouTube bot check",
                            ref={"episode": e["episode_id"]})
                if not yt_waited:
                    tried.discard(e["episode_id"])
                    log(f"YouTube bot check on {e['episode_id']}; YouTube episodes wait until the podcast audio is done")
                continue
            except Exception as exc:
                segs, tsrc, used = None, None, 0.0
                e["whisper_error"] = str(exc) if isinstance(exc, whisper.DownloadError) else type(exc).__name__
                rec = record_failure(run_dir, fails, e, exc)
            if segs and is_fallback(segs, min_chars):
                segs, e["whisper_error"] = None, "short"
            if segs:
                md = run_dir / e["file"]
                md.write_text(with_transcript(md.read_text(), segs, tsrc))
                e.update(has_transcript=True, transcript_source=tsrc, transcript_minutes=round(segs[-1]["start"] / 60),
                         fallback_text=False, transcript_chars=transcript_chars(segs))
                if store:
                    store.set_transcript(e["episode_id"], tsrc)
            elif not e.get("whisper_error"):
                e["whisper_error"] = "empty"
            changed = {k: v for k, v in e.items() if k not in before or before[k] != v}
            dropped = [k for k in before if k not in e]

            def apply(m):  # only this iteration's changes, onto the fresh manifest
                for row in m["episodes"]:
                    if row["episode_id"] == e["episode_id"]:
                        row.update(changed)
                        for k in dropped:
                            row.pop(k, None)
                m["whisper_minutes"] = round(m.get("whisper_minutes", 0) + (used if segs else 0) / 60, 1)
                if fails:
                    m.setdefault("failures", []).extend(fails["failures"])

            update_manifest(path, apply)
            episode_event(run_dir, e, bool(segs), time.monotonic() - t_ep, used, budget, tsrc, rec)
            done_ok, done_fail = done_ok + bool(segs), done_fail + (not segs)
            log(f"done {e['episode_id']} {tsrc or e.get('whisper_error')}")
    finally:
        for pf in prefetched.values():
            pf.cleanup()
        lock.unlink(missing_ok=True)

        def finish(m):
            timing_apply(m, "transcribe", "end")
            yt_left = {e["episode_id"] for e in m["episodes"] if yt_blocked is not None and not e.get("audio_url")}
            for row in m["episodes"]:
                why = skip_reason(row, top=top, skip_news=skip_news, reruns=reruns, retry=retry, tried=tried, yt_left=yt_left, budget=budget)
                row.pop("transcribe_skip", None)
                if why:
                    row["transcribe_skip"] = why

        try:
            update_manifest(path, finish)
        except (OSError, ValueError):
            pass
    events.note(transcribed=done_ok, failed=done_fail, whisper_min=round(budget.used / 60, 1))
    log(f"finished, {round(budget.used / 60, 1)} min used")
    return run_dir


NEWS = re.compile(r"halftime|squawk|power lunch|closing bell|fast money|mad money|news briefing|morning briefing|"
                  r"the exchange|worldwide exchange|markets daily|bloomberg surveillance", re.I)


def is_news(e: dict) -> bool:
    return bool(e.get("news")) or bool(NEWS.search(f"{e.get('source', '')} {e.get('source_tag', '')}"))


def pid_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


TRACKER = re.compile(r"^(dts\.podtrac\.com/redirect\.mp3/|www\.podtrac\.com/pts/redirect\.mp3/|chtbl\.com/track/[^/]+/|"
                     r"pdst\.fm/e/|prfx\.byspotify\.com/e/|tracking\.swap\.fm/track/[^/]+/|claritaspod\.com/measure/|"
                     r"arttrk\.com/p/[^/]+/|verifi\.podscribe\.com/rss/p/|pfx\.vpixl\.com/[^/]+/|mgln\.ai/e/[^/]+/|op3\.dev/e/)")


def norm_audio(u: str | None) -> str:
    """Host + path of the enclosure with query and tracking-redirect prefixes (podtrac, swap.fm, ...) stripped."""
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u.split("?", 1)[0].lower())
    while (m := TRACKER.match(u)):
        u = re.sub(r"^https?://", "", u[m.end():])
    return u


def segments_from_md(text: str) -> list[dict]:
    def parse_ts(t: str) -> float:
        sec = 0
        for part in t.split(":"):
            sec = sec * 60 + int(part)
        return float(sec)

    body = text.partition("## Transcript")[2]
    out = []
    for line in body.splitlines():
        m = re.match(r"^\[([\d:]+)\]\s*(.*)$", line)
        if m:
            out.append({"start": parse_ts(m.group(1)), "speaker": None, "text": m.group(2)})
    return out


class ReuseIndex:
    """Transcripts already made in other run folders, keyed by episode id, enclosure, and show + title."""

    def __init__(self, runs: Path, exclude: Path | None = None):
        self.by = {}
        for mp in sorted(runs.glob("*/manifest.json")):
            if exclude and mp.parent.resolve() == exclude.resolve():
                continue
            try:
                eps = json.loads(mp.read_text()).get("episodes", [])
            except (OSError, ValueError):
                continue
            for e in eps:
                if e.get("has_transcript"):
                    for k in self.keys(e):
                        self.by.setdefault(k, (mp.parent, e))

    @staticmethod
    def keys(e: dict) -> list[str]:
        ks = [f"id:{e['episode_id']}"]
        if norm_audio(e.get("audio_url")):
            ks.append(f"audio:{norm_audio(e.get('audio_url'))}")
        if norm_title(e.get("title")):
            ks.append(f"title:{norm_title(e.get('source') or e.get('source_tag', '').split(',')[0])}|{norm_title(e['title'])}")
        return ks

    def locate(self, e: dict):
        """(run folder, manifest row) of an earlier transcript of this episode whose markdown is still on disk, else None."""
        for k in self.keys(e):
            if k in self.by:
                d, old = self.by[k]
                if k.startswith("title:") and different_youtube_videos(e["episode_id"], old["episode_id"], e.get("youtube_id"), old.get("youtube_id")):
                    continue
                if (d / old["file"]).exists():
                    return d, old
        return None

    def find(self, e: dict):
        for k in self.keys(e):
            if k in self.by:
                d, old = self.by[k]
                if k.startswith("title:") and different_youtube_videos(e["episode_id"], old["episode_id"], e.get("youtube_id"), old.get("youtube_id")):
                    continue
                md = d / old["file"]
                if md.exists():
                    segs = segments_from_md(md.read_text())
                    if segs and transcript_chars(segs) >= MIN_TRANSCRIPT_CHARS:
                        return segs, old["transcript_source"], f"{d.name}/{old['file']}", old.get("transcript_url")
        return None


def can_whisper(e: dict) -> bool:
    """Audio to download: the feed enclosure, or else a YouTube video (yt-dlp audio)."""
    return bool(e.get("audio_url") or e.get("youtube_id"))


def refresh_flags(manifest: dict, run_dir: Path, min_chars: int) -> dict:
    for e in manifest["episodes"]:
        md = run_dir / e["file"]
        head, _, body = (md.read_text() if md.exists() else "").partition("## Transcript")
        text = re.sub(r"^\[[\d:]+\]\s*", "", body, flags=re.M).strip()
        e.setdefault("rerun", is_rerun(e["title"], head.partition("## Description")[2]))
        if e["has_transcript"] and len(text) < min_chars:
            e.update(has_transcript=False, fallback_text=True, fallback_from=e["transcript_source"],
                     transcript_source="fallback", transcript_chars=len(text), transcript_minutes=0)
            e.pop("whisper_error", None)
            log(f"fallback {e['episode_id']} ({len(text)} chars) {e['title'][:60]}")
    return manifest


def log(msg: str) -> None:
    print(f"[transcribe] {datetime.now().strftime('%H:%M:%S')} {msg}", flush=True)


def with_transcript(md: str, segs: list[dict], tsrc: str) -> str:
    head, _, _ = md.partition("## Transcript")
    head = re.sub(r"^transcript_source: .*$", f"transcript_source: {tsrc}", head, count=1, flags=re.M)
    lines = [f"[{fmt_ts(s['start'])}] {s['speaker'] + ': ' if s.get('speaker') else ''}{s['text']}" for s in segs]
    return head + "## Transcript\n\n" + "\n".join(lines) + "\n"


ROOT = Path(__file__).resolve().parent.parent


def has_whisper(python: str) -> bool:
    import subprocess

    try:
        code = "import sys, sigma.whisper as w; sys.exit(0 if w.available() else 1)"  # mlx or faster, per SIGMA_WHISPER_BACKEND
        return subprocess.run([python, "-c", code], capture_output=True, timeout=120,
                              cwd=ROOT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def whisper_python() -> str:
    """Interpreter for the background transcribe: SIGMA_PYTHON, this one, then the repo .venv."""
    cands = [os.environ.get("SIGMA_PYTHON"), sys.executable, str(ROOT / ".venv" / "bin" / "python")]
    for c in dict.fromkeys(x for x in cands if x):
        if (c == sys.executable or Path(c).exists()) and has_whisper(c):
            return c
    raise SystemExit("[daily] no interpreter with mlx_whisper or faster_whisper (tried " + ", ".join(x for x in cands if x) +
                     "). Install with `pip install -e '.[whisper]'` (Mac: `'.[whisper,mac]'`) or set SIGMA_PYTHON; rerun with --no-transcribe to skip.")


def queue_transcribe(run_dir: Path, minutes: float, db: str | None, python: str | None = None, news: bool = False,
                     top: int = DEFAULT_TOP, people: str | None = None, tier1_floor: bool = True) -> int:
    import subprocess

    cmd = [python or whisper_python(), "-m", "sigma.cli", "transcribe", str(run_dir), "--minutes", str(minutes)]
    if db:
        cmd += ["--db", db]
    if news:
        cmd.append("--news")
    cmd += ["--top", str(top)] + (["--people", str(people)] if people else []) + ([] if tier1_floor else ["--no-tier1-floor"])
    with open(run_dir / "transcribe.log", "a") as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True,
                                cwd=Path(__file__).resolve().parent.parent)
    # The child takes transcribe.lock a moment after it starts; until then `status` reads this marker as "starting".
    # (Not the lock itself: the child refuses a lock naming a live pid.)
    (run_dir / "transcribe.queued").write_text(str(proc.pid))
    return proc.pid


def daily(args) -> Path:
    args.days, args.people_first = args.hours / 24, True
    python = None if args.no_transcribe else whisper_python()  # fail fast, before the slow fetch
    run_dir = fetch(args)
    from .timing import errored_sources

    health = json.loads((run_dir / "manifest.json").read_text()).get("sources") or {}
    bad = errored_sources(health)
    print(f"[daily] source errors {len(bad)}/{len(health)}: {'; '.join(bad)}" if bad else
          f"[daily] source errors 0/{len(health)}")
    events.note(sources=len(health), source_errors=len(bad))
    if args.no_transcribe:
        print(f"[daily] transcribe later: .venv/bin/sigma transcribe {run_dir}")
    else:
        pid = queue_transcribe(run_dir, args.minutes, args.db, python, getattr(args, "news", False),
                               getattr(args, "top", DEFAULT_TOP), getattr(args, "people", None),
                               not getattr(args, "no_tier1_floor", False))
        print(f"[daily] transcribe queued pid={pid} python={python} log={run_dir / 'transcribe.log'}")
    return run_dir
