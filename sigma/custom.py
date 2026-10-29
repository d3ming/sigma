"""Custom runs: search for candidate episodes (`find`), then build a run folder from the ones an agent picked (`custom-run`).

The code supplies the mechanical steps; the agent decides which candidates are worth covering and what they said.
`find` searches without creating anything; `custom-run` builds the run folder; `transcribe` and `status` then work on it as on any
run. To put the set on the site as a one-off issue, rank it like a week (`rank-prep`, readers following prompts/rank.md,
`rank-merge --week-of <issue date>`), add a "title" to ranked.json and `publish` it: the site lists it under Special issues with
that title in place of "Week of", and the digest uses it too.
"""
from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import people as ppl
from .fetch import ReuseIndex, write_episode
from .ingest import Episode, parse_date
from .manifest import update as update_manifest
from .transcribe import title_match

DATE_SLACK_DAYS = 2  # the same episode is posted a day or two apart on podcast apps and YouTube
REQUIRED = ("episode_id", "title", "show", "published")


def same_episode(a: dict, b: dict) -> bool:
    """Same id, or nearly the same title published within a couple of days (an episode and its YouTube copy)."""
    if a["episode_id"] == b["episode_id"]:
        return True
    da, db = parse_date(a["published"]), parse_date(b["published"])
    if not da or not db or abs((da - db).total_seconds()) > DATE_SLACK_DAYS * 86400:
        return False
    return title_match(a["title"], b["title"]) >= 0.8


def candidate(ep: Episode, finder: str, person: ppl.Person | None = None, query: str | None = None) -> dict:
    return {"episode_id": ep.id, "title": ep.title, "show": ep.source_name, "published": ep.published_at.isoformat(),
            "url": ep.url, "audio_url": ep.audio_url, "youtube_id": ep.youtube_id, "feed_url": ep.feed_url,
            "description": ep.description or "", "duration": ep.duration,
            "minutes": round(ep.duration / 60) if ep.duration else None,
            "people": [person.name] if person else [], "queries": [query] if query else [], "via": [finder],
            "role": person.role if person and person.role else None, "transcribed": None}


def merge_candidates(found: list[dict]) -> list[dict]:
    """Collapse the same episode found by several searches; a copy with audio goes first so its id and links lead."""
    out: list[dict] = []
    for c in sorted(found, key=lambda c: not c["audio_url"]):
        dup = next((o for o in out if same_episode(o, c)), None)
        if not dup:
            out.append(c)
            continue
        for k in ("people", "queries", "via"):
            dup[k] += [x for x in c[k] if x not in dup[k]]
        for k in ("audio_url", "youtube_id", "feed_url", "duration", "minutes", "role"):
            dup[k] = dup[k] or c[k]
        if len(c["description"]) > len(dup["description"]):
            dup["description"] = c["description"]
    return sorted(out, key=lambda c: c["published"], reverse=True)


def search(people: list[ppl.Person], queries: list[str], now: datetime, days: int, youtube: bool = True, min_minutes: int = 20,
           workers: int = 3) -> tuple[list[dict], list[str]]:
    """(deduped candidates, error strings). A failed search (rate limit, YouTube blocking this IP) is reported, not fatal."""
    jobs = []  # (label, finder name, call, person, query)
    for p in people:
        jobs.append((f"{p.name}/itunes", "itunes", lambda p=p: ppl.from_itunes(p, now, days, min_minutes=min_minutes), p, None))
        if youtube:
            jobs.append((f"{p.name}/youtube", "youtube", lambda p=p: ppl.from_youtube_search(p, now, days, limit=8, min_minutes=min_minutes), p, None))
    for q in queries:
        jobs.append((f"{q!r}/itunes", "itunes", lambda q=q: ppl.from_itunes_query(q, now, days, min_minutes=min_minutes), None, q))
        if youtube:
            jobs.append((f"{q!r}/youtube", "youtube", lambda q=q: ppl.from_youtube_query(q, now, days, limit=8, min_minutes=min_minutes), None, q))

    def run(job):
        try:
            return job[2](), None
        except Exception as exc:  # one search failing must not hide the others
            return None, exc

    with ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as pool:
        results = list(pool.map(run, jobs))
    found, errors = [], []
    for (label, finder, _, person, query), (eps, exc) in zip(jobs, results):
        if exc is not None:
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:100]}")
            continue
        found += [candidate(e, finder, person, query) for e in eps]
    return merge_candidates(found), errors


def mark_transcribed(cands: list[dict], runs: Path) -> None:
    """Set `transcribed` on candidates whose transcript already sits in a run folder under `runs`."""
    reuse = ReuseIndex(runs)
    for c in cands:
        hit = reuse.locate({"episode_id": c["episode_id"], "audio_url": c["audio_url"], "title": c["title"], "source": c["show"]})
        if hit:
            c["transcribed"] = {"run": hit[0].name, "file": hit[1]["file"], "source": hit[1].get("transcript_source")}


def line(c: dict) -> str:
    who = ", ".join(c["people"] + [f"'{q}'" for q in c["queries"]])
    free = f"  [transcribed in {c['transcribed']['run']}]" if c["transcribed"] else ""
    mins = f"{c['minutes']:>3} min" if c["minutes"] else "  ? min"
    return f"{c['published'][:10]}  {mins}  {c['show'][:28]} | {c['title'][:80]} | {who} | {'+'.join(c['via'])}{free}"


def load_picks(path: str | Path) -> list[dict]:
    try:
        picks = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"[custom-run] cannot read {path}: {exc}")
    if not isinstance(picks, list) or not all(isinstance(p, dict) for p in picks):
        sys.exit(f"[custom-run] {path} must be a JSON list of candidates, as `sigma find --json` prints them")
    for i, p in enumerate(picks):
        if missing := [k for k in REQUIRED if not p.get(k)]:
            sys.exit(f"[custom-run] pick {i} ({p.get('title', '?')[:50]}) is missing {', '.join(missing)}")
        if not parse_date(p["published"]):
            sys.exit(f"[custom-run] pick {i} ({p['title'][:50]}): cannot read published {p['published']!r}")
        if not (p.get("audio_url") or p.get("youtube_id")):
            sys.exit(f"[custom-run] pick {i} ({p['title'][:50]}) has neither audio_url nor youtube_id, so it cannot be transcribed")
    return picks


def to_episode(pick: dict) -> Episode:
    tag = f"person:{pick['people'][0]}" if pick.get("people") else f"query:{pick['queries'][0]}" if pick.get("queries") else "custom"
    return Episode(id=pick["episode_id"], source_id=tag, source_name=pick["show"], tier=2, title=pick["title"],
                   url=pick.get("url") or "", published_at=parse_date(pick["published"]), youtube_id=pick.get("youtube_id"),
                   audio_url=pick.get("audio_url"), feed_url=pick.get("feed_url"), description=pick.get("description") or "",
                   via="+".join(pick.get("via") or []) or "custom", duration=pick.get("duration"))


def build_run(run_dir: Path, picks: list[dict], note: str | None = None, sources: str | None = None,
              now: datetime | None = None) -> dict:
    """Write one .md and one manifest row per new pick under run_dir; reuse transcripts other runs already hold.
    Rerunning adds only the picks not already there, and is safe while `transcribe` runs on the folder (the manifest is updated
    under its lock). It does not write the dedupe database (fetch's `store`), so a later daily can still pick the same episode.
    Returns {added, reused, skipped}."""
    now = now or datetime.now(timezone.utc)
    path = run_dir / "manifest.json"
    prior = json.loads(path.read_text()) if path.exists() else None
    if prior and prior.get("kind") != "custom":
        sys.exit(f"[custom-run] {run_dir} is a {prior.get('kind') or 'daily/weekly'} run, not a custom run; pick another name")
    have = [{"episode_id": e["episode_id"], "title": e["title"], "published": e["published"]} for e in (prior or {}).get("episodes", [])]
    run_dir.mkdir(parents=True, exist_ok=True)
    reuse = ReuseIndex(run_dir.parent, exclude=run_dir)
    tiers = None
    if sources and Path(sources).exists():
        from .config import load_sources

        tiers = load_sources(sources)[0]
    rows, skipped, reused = [], [], 0
    for pick in picks:
        if any(same_episode(pick, h) for h in have):
            skipped.append(pick["episode_id"])
            print(f"[custom-run] already in run: {pick['title'][:70]}")
            continue
        ep = to_episode(pick)
        if tiers:
            ppl.apply_source_tiers([ep], tiers)
        hit = reuse.find({"episode_id": ep.id, "audio_url": ep.audio_url, "title": ep.title, "source": ep.source_name})
        segs, tsrc = (hit[0], hit[1]) if hit else (None, None)
        if hit:
            ep.transcript_url = hit[3]
            reused += 1
            print(f"[custom-run] reuse transcript from {hit[2]}")
        row = write_episode(run_dir, ep, segs, tsrc)
        # The agent chose it on purpose, so a "replay" in the title is not a reason to drop it.
        row.update(rerun=False, matched=(pick.get("people") or []) + (pick.get("queries") or []))
        if hit:
            row["reused_from"] = hit[2]
        rows.append(row)
        have.append({"episode_id": ep.id, "title": ep.title, "published": pick["published"]})

    oldest = min([parse_date(h["published"]) for h in have if parse_date(h["published"])] or [now])
    entry = {"at": now.isoformat(timespec="seconds"), "added": len(rows), "reused": reused}

    def apply(m):
        ids = {e["episode_id"] for e in m.setdefault("episodes", [])}
        m["episodes"] += [r for r in rows if r["episode_id"] not in ids]
        m.setdefault("custom", []).append(entry)
        m["days"] = max(m.get("days") or 0, math.ceil((now - oldest).total_seconds() / 86400))
        if note:
            m["note"] = note

    update_manifest(path, apply, lambda: {"run_at": now.isoformat(timespec="seconds"), "days": 0, "kind": "custom",
                                          "episodes": [], "skipped_seen": []})
    return {"added": len(rows), "reused": reused, "skipped": skipped}
