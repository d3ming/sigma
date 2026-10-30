"""Onboarding a show: `sigma source add <url>` puts it in sources.yaml, `sigma source review` says which tiers the scores support.

`--style influencer` marks a creator who picks stocks: those episodes are scored apart from interviews (sigma/rank.py).

A new show starts at tier 2: triage picks its best episodes for transcription and the rest wait. Tier 1 means every
non-news episode is transcribed, so a show earns it by scoring well (see `review`), not by being liked.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import urllib.parse
from collections import defaultdict
from datetime import date
from pathlib import Path

from .config import Source, load_sources
from .entities import ENTITIES_FILE, slug
from .links import _get, similar
from .showlinks import fill, name_like

PROMOTE_MIN_EPISODES, PROMOTE_MEAN, PROMOTE_SHARE = 3, 6.0, 0.5  # tier 2 -> 1: 3+ scored, mean 6+ and half at the site bar
DEMOTE_MIN_EPISODES, DEMOTE_MEAN = 5, 5.0  # tier 1 -> 2: 5+ scored and a mean under 5
YOUTUBE = re.compile(r"(?:youtube\.com|youtu\.be)/", re.I)
APPLE = re.compile(r"podcasts\.apple\.com/.*?/id(\d+)", re.I)


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s).lower()).split())


def find_existing(sources: list[Source], name: str = "", rss: str = "", itunes_id: int | None = None, channel_id: str = "",
                  link_channels: dict | None = None) -> Source | None:
    """The source that already covers this show: same feed, Apple id, YouTube channel (on the source or in show_links.yaml,
    where a channel often sits under a different name than the show), or exact name or alias."""
    for s in sources:
        if (rss and s.rss and s.rss.rstrip("/") == rss.rstrip("/")) or (itunes_id and s.itunes_id == itunes_id) \
                or (channel_id and channel_id in ((link_channels or {}).get(s.id) or []) + [s.youtube_channel_id]) \
                or (name and norm(name) in {norm(s.name), *map(norm, s.aliases)}):
            return s
    return None


def _ytdlp(url: str) -> tuple[str, str]:
    """(channel id, channel name) of a YouTube video or channel url, through yt-dlp."""
    import subprocess

    target = url if re.search(r"watch\?v=|youtu\.be/", url) else url.rstrip("/") + "/videos"
    out = subprocess.run([sys.executable, "-m", "yt_dlp", "--skip-download", "--playlist-items", "1:4", "--print",
                          "%(channel_id)s\t%(channel)s", target], capture_output=True, text=True, timeout=180).stdout.strip().splitlines()
    # the newest item can be a live stream or premiere that reports no channel, so take the first that does
    cid, _, channel = next((l for l in out if l.startswith("UC")), "").partition("\t")
    if not cid.startswith("UC"):
        raise SystemExit(f"[source] could not read a YouTube channel from {url}")
    return cid, channel


def _itunes_by_name(name: str, get) -> dict:
    q = urllib.parse.urlencode({"term": name, "media": "podcast", "entity": "podcast", "limit": 10})
    for h in get(f"https://itunes.apple.com/search?{q}").get("results", []):
        if h.get("feedUrl") and name_like(name, h.get("collectionName", "")) and similar(name, h["collectionName"]) >= 0.8:
            return h
    return {}


def resolve(url: str, get=_get, ytdlp=_ytdlp, parse=None) -> dict:
    """{name, rss, itunes_id, youtube_channel_id} for an Apple Podcasts, YouTube or feed url. Keys it cannot find are empty."""
    out = {"name": "", "rss": "", "itunes_id": None, "youtube_channel_id": ""}
    hit: dict = {}
    if m := APPLE.search(url):
        hit = (get(f"https://itunes.apple.com/lookup?id={m.group(1)}").get("results") or [{}])[0]
    elif YOUTUBE.search(url):
        out["youtube_channel_id"], out["name"] = ytdlp(url)
        # a podcast that only shares the channel's name may be someone else's or long dead: suggest it, never attach it
        if h := _itunes_by_name(out["name"], get):
            out["apple_hint"] = f'{h.get("collectionName")} (https://podcasts.apple.com/podcast/id{h.get("collectionId")})'
    else:
        import feedparser

        feed = (parse or feedparser.parse)(url)
        out["name"], out["rss"] = (feed.feed.get("title") or "").strip(), url
        hit = _itunes_by_name(out["name"], get) if out["name"] else {}
        hit = hit if hit.get("feedUrl", "").rstrip("/") == url.rstrip("/") else {}
    if hit:
        out["name"] = out["name"] or hit.get("collectionName", "")
        out["rss"] = out["rss"] or hit.get("feedUrl", "")
        out["itunes_id"] = hit.get("collectionId")
    return out


def source_line(s: dict) -> str:
    """One flow-style entry in the file's own style."""
    parts = [f'id: {s["id"]}', f'name: {json.dumps(s["name"], ensure_ascii=False)}', f'tier: {s["tier"]}']
    if s.get("style", "interview") != "interview":
        parts.append(f'style: {s["style"]}')
    if s.get("rss"):
        parts.append(f'rss: "{s["rss"]}"')
    if s.get("youtube_channel_id"):  # the channel is the fallback when the feed fails or goes stale
        parts.append(f'youtube: "https://www.youtube.com/channel/{s["youtube_channel_id"]}/videos"')
    if s.get("itunes_id"):
        parts.append(f'itunes_id: {s["itunes_id"]}')
    if s.get("youtube_channel_id") and s.get("rss"):
        parts.append(f'youtube_channel_id: {s["youtube_channel_id"]}')
    parts.append(f'topics: [{", ".join(s.get("topics") or [])}]')
    if s.get("news"):
        parts.append("news: true")
    return "  - {" + ", ".join(parts) + "}"


def add_cmd(args) -> None:
    sources_path, links_path, ent_path = Path(args.sources), Path(args.links), Path(args.entities)
    existing, _ = load_sources(sources_path)
    found = resolve(args.url)
    import yaml

    shown = yaml.safe_load(links_path.read_text()) if links_path.exists() else {}
    chans = {sid: re.findall(r"UC[\w-]{22}", str((row or {}).get("youtube") or "")) for sid, row in (shown or {}).items()}
    hit = find_existing(existing, found["name"], found["rss"], found["itunes_id"], found["youtube_channel_id"], chans)
    if hit:
        print(f'[source] already a source: "{hit.name}" ({hit.id}), tier {hit.tier}; nothing added. '
              f'Change the tier by editing its line in {sources_path.name} (`sigma source review` says when).')
        return
    name = args.name or found["name"]
    if not name or not (found["rss"] or found["youtube_channel_id"]):
        raise SystemExit(f"[source] could not find a feed or channel for {args.url}; pass an Apple Podcasts, YouTube or feed url")
    if args.style == "influencer" and not found["youtube_channel_id"]:
        raise SystemExit(f"[source] an influencer is added from its YouTube channel (YouTube is Social's primary source); "
                         f"{args.url} gave no channel. Pass the creator's YouTube channel or video url")
    ents = json.loads(ent_path.read_text(encoding="utf-8")) if ent_path.exists() else {}
    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()]
    bad = [t for t in topics if t not in (ents.get("topic_names") or {})]
    if bad:
        raise SystemExit(f"[source] unknown topic {bad}; topics in entities.json: {', '.join(ents.get('topic_names') or {})}")
    sid = args.id or slug(name)
    if any(s.id == sid for s in existing):
        raise SystemExit(f'[source] id "{sid}" is taken by another show; pass --id')
    entry = {"id": sid, "name": name, "tier": args.tier, "style": args.style, "topics": topics, "news": args.news, **{k: found[k] for k in ("rss", "itunes_id", "youtube_channel_id")}}
    line = source_line(entry)
    styled = "" if args.style == "interview" else f", style {args.style}"
    text = sources_path.read_text(encoding="utf-8").rstrip("\n")
    new = f"{text}\n  # Added {date.today().isoformat()} at tier {args.tier}{styled} until its episodes are scored.\n{line}\n"
    if args.dry_run:
        print(f"[source] dry run, would append to {sources_path.name}:\n{line}")
        return
    tmp = sources_path.with_suffix(".check.yaml")
    tmp.write_text(new, encoding="utf-8")
    try:
        load_sources(tmp)
    finally:
        tmp.unlink()
    sources_path.write_text(new, encoding="utf-8")
    print(f'[source] added "{name}" ({sid}) at tier {args.tier}{styled}\n{line}')
    if topics:
        from .site import person_slug

        ents.setdefault("show_topics", {})[person_slug(name)] = topics
        ent_path.write_text(json.dumps(ents, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[source] topics {topics} written to {ent_path.name}")
    else:
        print("[source] no topics: pass --topics (e.g. --topics ai,tech) or edit entities.json; `sigma entities check` lists shows without one")
    try:
        got = fill(sources_path, links_path, only={sid}).get(sid, [])
        print(f"[source] show links filled: {', '.join(got) or 'none found'}")
    except Exception as e:  # the show is added either way; links are cosmetic
        print(f"[source] show links not filled ({e}); run `sigma show-links --only {sid}` later")
    if found.get("apple_hint"):
        print(f"[source] Apple has a podcast with this name: {found['apple_hint']}. If it is the same show and still active, "
              "add its feed by hand (rss and itunes_id); it was not attached")
    print(f"[source] the next daily fetches it. After {PROMOTE_MIN_EPISODES} scored episodes `sigma source review` suggests a tier.")


def stats_by_source(sources: list[Source], published: Path) -> dict:
    """{source id: scores, newest first} from published/, matching a show to its source by name or alias. These are interview scores
    only (the site's episode registry leaves influencer episodes out), so a `style: influencer` source has none to review yet."""
    from . import site

    reg = site.build_episodes(site.load_runs(published))
    by_name = {}
    for s in sources:
        for n in [s.name, *s.aliases]:
            by_name[norm(n)] = s.id
    scores: dict[str, list] = defaultdict(list)
    for e in sorted(reg.values(), key=lambda e: e.get("published") or "", reverse=True):
        sid = by_name.get(norm(e.get("show") or ""))
        if sid and isinstance(e.get("score"), int):
            scores[sid].append(e["score"])
    return scores


def advice(tier: int, scores: list[int], bar: int) -> str:
    """A suggestion, never an edit: the tier is changed by hand in sources.yaml. A tier-2 show's scores come from the episodes triage
    chose to transcribe, so they run high; treat `promote to tier 1` as a prompt to look, not a verdict."""
    n = len(scores)
    mean = statistics.mean(scores) if n else 0
    share = sum(s >= bar for s in scores) / n if n else 0
    if tier == 2 and n >= PROMOTE_MIN_EPISODES and mean >= PROMOTE_MEAN and share >= PROMOTE_SHARE:
        return "promote to tier 1"
    if tier == 1 and n >= DEMOTE_MIN_EPISODES and mean < DEMOTE_MEAN:
        return "consider tier 2"
    if tier == 2 and n < PROMOTE_MIN_EPISODES:
        return f"{PROMOTE_MIN_EPISODES - n} more scored episodes to judge" if n else "no scored episodes yet"
    return "keep"


def review_cmd(args) -> None:
    from . import site
    from .site import person_slug

    sources, _ = load_sources(args.sources)
    scores = stats_by_source(sources, Path(args.published))
    ents = json.loads(Path(args.entities).read_text(encoding="utf-8")) if Path(args.entities).exists() else {}
    links = {}
    if Path(args.links).exists():
        import yaml

        links = yaml.safe_load(Path(args.links).read_text()) or {}
    rows = []
    for s in sources:
        sc = scores.get(s.id, [])
        gaps = [g for g, bad in (("topics", not (ents.get("show_topics") or {}).get(person_slug(s.name))),
                                 ("links", not all((links.get(s.id) or {}).get(f) for f in ("apple", "youtube")))) if bad]
        rows.append((s, sc, advice(s.tier, sc, site.BAR), gaps))
    print(f"{'source':34} tier  n  mean  >={site.BAR}  advice")
    for s, sc, adv, gaps in sorted(rows, key=lambda r: (r[0].tier, r[0].id)):
        mean = f"{statistics.mean(sc):4.1f}" if sc else "   -"
        share = f"{sum(x >= site.BAR for x in sc)}/{len(sc)}" if sc else "-"
        print(f"{s.name[:34]:34} {s.tier:>4} {len(sc):>2}  {mean}  {share:>4}  {adv}" + (f"  (missing: {', '.join(gaps)})" if gaps else ""))
