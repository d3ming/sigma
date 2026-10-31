from __future__ import annotations

import hashlib
import re
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


from .config import Source
from .feedcache import image_url


@dataclass
class Episode:
    id: str
    source_id: str
    source_name: str
    tier: int
    title: str
    url: str
    published_at: datetime
    youtube_id: str | None = None
    transcript_urls: list | None = None
    transcript_url: str | None = None  # where a reader can open the transcript we used; set by get_transcript
    audio_url: str | None = None
    description: str = ""
    via: str = ""
    methods: list | None = None
    feed_url: str | None = None
    duration: int | None = None  # seconds, when the feed/search reports it
    style: str = "interview"  # the show's style in sources.yaml; influencer episodes are scored apart (sigma/rank.py)
    image_url: str | None = None
    show_image_url: str | None = None


def canonical_id(guid: str | None, youtube_id: str | None, link: str | None) -> str:
    if guid:
        return "rss:" + hashlib.sha1(guid.encode()).hexdigest()[:16]
    if youtube_id:
        return "yt:" + youtube_id
    return "url:" + hashlib.sha1((link or "").encode()).hexdigest()[:16]


def different_youtube_videos(first_id: str, second_id: str, first_video: str | None = None, second_video: str | None = None) -> bool:
    first_video = first_video or (first_id[3:] if first_id.startswith("yt:") else None)
    second_video = second_video or (second_id[3:] if second_id.startswith("yt:") else None)
    return bool(first_video and second_video and first_video != second_video)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


UA = {"User-Agent": "sigma/0.1 (+https://github.com/d3ming/sigma)"}
RERUN = re.compile(r"\b(replay|re-?air(ed|ing)?|rebroadcast|encore|rerun|best of|from the archive|originally (aired|released|published))\b", re.I)


def is_rerun(title: str, description: str = "") -> bool:
    return bool(RERUN.search(title or "") or RERUN.search((description or "")[:400]))


def parse_duration(v) -> int | None:
    """itunes:duration: seconds, MM:SS or HH:MM:SS."""
    try:
        parts = [int(float(x)) for x in str(v).strip().split(":")]
    except (TypeError, ValueError):
        return None
    if not parts or len(parts) > 3:
        return None
    sec = 0
    for x in parts:
        sec = sec * 60 + x
    return sec or None


def in_window(dt: datetime, now: datetime, days: int) -> bool:
    return now - timedelta(days=days) <= dt <= now + timedelta(hours=1)


def transcript_links(entry) -> list[dict]:
    links = []
    for key in ("podcast_transcript",):
        val = entry.get(key)
        if isinstance(val, dict):
            links.append(val)
        elif isinstance(val, list):
            links.extend(v for v in val if isinstance(v, dict))
    for link in entry.get("links", []):
        if link.get("rel") == "transcript" or "transcript" in (link.get("type") or ""):
            links.append({"url": link.get("href"), "type": link.get("type")})
    return [l for l in links if l.get("url")]


AUDIO_URL = re.compile(r"\.(mp3|m4a|aac|ogg|opus|wav)(\?|$)|podtrac|swap\.fm|traffic\.megaphone|/redirect\.mp3|chtbl\.com|pdst\.fm", re.I)


def page_url(entry, audio: str | None, feed_link: str | None = None) -> str:
    """Episode page for display. In order: item link, item id/guid when it is itself a page URL, other non-audio
    alternate links, then the show page. Enclosure, audio and tracking URLs never qualify; nothing is invented."""
    guid = entry.get("id") or entry.get("guid")
    cands = [entry.get("link"), guid if isinstance(guid, str) and re.match(r"https?://", guid) else None]
    cands += [l.get("href") for l in entry.get("links", [])
              if l.get("rel") in (None, "alternate") and not (l.get("type") or "").startswith("audio")]
    for u in cands:
        if u and u != audio and not AUDIO_URL.search(u):
            return u
    return feed_link if feed_link and not AUDIO_URL.search(feed_link) else ""


STALE_FEED_DAYS = 45  # a show with no feed episode this long has usually moved to YouTube or stopped


def from_rss(src: Source, now: datetime, days: int, parsed=None) -> list[Episode]:
    """Episodes in the window. Without `parsed`, the feed comes through feedcache (conditional GET, parse in a worker process)."""
    from . import feedcache

    if parsed is None:
        data = feedcache.load_feed(src.rss)
    else:  # an already-parsed feedparser result (tests, callers that parsed it themselves)
        data = feedcache.reduce_parsed(parsed)
        if data["error"]:
            raise ValueError(f"no entries from {src.rss}: {data['error']}")
    dates = [d for e in data["entries"] if (d := parse_date(e.get("published") or e.get("updated")))]
    if dates and max(dates) < now - timedelta(days=STALE_FEED_DAYS):
        # a feed the show stopped updating (it moved to YouTube) fails like a dead one, so find() tries the next finder
        raise ValueError(f"stale feed {src.rss}: newest entry {max(dates).date()}")
    out = []
    for e in data["entries"]:
        dt = parse_date(e.get("published") or e.get("updated"))
        if not dt or not in_window(dt, now, days):
            continue
        audio = next((l.get("href") for l in e.get("links", []) if (l.get("type") or "").startswith("audio")), None)
        out.append(Episode(
            id=canonical_id(e.get("id") or e.get("guid"), None, e.get("link")),
            source_id=src.id, source_name=src.name, tier=src.tier, style=src.style,
            title=e.get("title", "").strip(), url=page_url(e, audio, data["link"]),
            published_at=dt, transcript_urls=transcript_links(e), audio_url=audio,
            description=e.get("summary", "")[:2000], duration=parse_duration(e.get("itunes_duration")),
            image_url=e.get("image_url") or data.get("image_url"),
            show_image_url=data.get("image_url"),
        ))
    return out


def _yt_json(args: list[str]) -> list[dict]:
    res = subprocess.run([sys.executable, "-m", "yt_dlp", "-j", "--skip-download", "--no-warnings", "--sleep-requests", "1", *args],
                         capture_output=True, text=True, timeout=300)
    return [json.loads(l) for l in res.stdout.splitlines() if l.strip()]


def from_youtube(src: Source, now: datetime, days: int, max_items: int = 8) -> list[Episode]:
    out = []
    for v in _yt_json(["--flat-playlist", "-I", f"1:{max_items}", src.youtube]):
        info = _yt_json([f"https://www.youtube.com/watch?v={v['id']}"])
        if not info:
            continue
        info = info[0]
        ts = info.get("release_timestamp") or info.get("timestamp")
        if ts:
            dt = datetime.fromtimestamp(ts, timezone.utc)
        elif info.get("upload_date"):
            dt = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
        else:
            continue
        if not in_window(dt, now, days):
            if dt < now - timedelta(days=days):
                break
            continue
        if (info.get("duration") or 0) < 300:
            continue
        out.append(Episode(
            id=canonical_id(None, v["id"], None), source_id=src.id, source_name=src.name, tier=src.tier, style=src.style,
            title=info.get("title", ""), url=f"https://www.youtube.com/watch?v={v['id']}",
            published_at=dt, youtube_id=v["id"], description=(info.get("description") or "")[:2000],
            duration=int(info["duration"]) if info.get("duration") else None,
            image_url=image_url(info.get("thumbnail")),
        ))
    return out


def from_itunes(src: Source, now: datetime, days: int, get=None) -> list[Episode]:
    """Apple's copy of the show's episode list, for when the feed host is down. Apple keeps the feed's guid, so an
    episode gets the same id here as from the feed. Apple refreshes every few hours, so the newest may lag."""
    import requests

    r = (get or requests.get)("https://itunes.apple.com/lookup", timeout=30,
                              params={"id": src.itunes_id, "entity": "podcastEpisode", "limit": 20})
    r.raise_for_status()
    results = r.json().get("results", [])
    show_image = next((art for e in results if e.get("wrapperType") == "track" and e.get("kind") == "podcast"
                       and e.get("collectionId") == src.itunes_id
                       and (art := image_url(e.get("artworkUrl600") or e.get("artworkUrl100")))), None)
    rows = [e for e in results if e.get("wrapperType") == "podcastEpisode"]
    dates = [d for e in rows if (d := parse_date(e.get("releaseDate")))]
    if dates and max(dates) < now - timedelta(days=STALE_FEED_DAYS):
        raise ValueError(f"stale on Apple too: newest episode {max(dates).date()}")  # Apple mirrors the stale feed
    out = []
    for e in rows:
        dt = parse_date(e.get("releaseDate"))
        if e.get("wrapperType") != "podcastEpisode" or not dt or not in_window(dt, now, days):
            continue
        out.append(Episode(
            id=canonical_id(e.get("episodeGuid"), None, e.get("trackViewUrl")),
            source_id=src.id, source_name=src.name, tier=src.tier, style=src.style,
            title=e.get("trackName", "").strip(), url=e.get("trackViewUrl") or e.get("episodeUrl", ""),
            published_at=dt, audio_url=e.get("episodeUrl"), description=(e.get("description") or "")[:2000],
            duration=round(e["trackTimeMillis"] / 1000) if e.get("trackTimeMillis") else None,
            image_url=image_url(e.get("artworkUrl600") or e.get("artworkUrl160")),
            show_image_url=show_image,
        ))
    return out


FINDERS = {"rss": from_rss, "itunes": from_itunes, "ytdlp": from_youtube}


def find(src: Source, now: datetime, days: int) -> tuple[list[Episode], str]:
    errors = []
    for how in src.order:
        try:
            eps = FINDERS[how](src, now, days)
        except Exception as exc:
            errors.append(f"{how}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        for e in eps:
            e.via, e.methods = e.via or how, src.transcripts or None
        return eps, how
    if errors and all("stale" in e for e in errors):
        return [], "stale"  # every route is just quiet (an annual meeting, an event-only show): no error to report
    raise LookupError("; ".join(errors) or "no usable source")


def discover(sources: list[Source], now: datetime, days: int, t3_cap: int, per_source: int = 3,
             health: dict | None = None) -> list[Episode]:
    """health, if given, gets {source id: {via, found (in window, before caps), kept, error, capped (title + date of each
    episode dropped by the per-source or tier-3 cap, so a cap never loses one silently)}}."""
    eps: list[Episode] = []
    t3 = 0
    health = {} if health is None else health

    def look(src):
        try:
            return find(src, now, days), None
        except Exception as exc:
            return None, exc

    # Feeds are independent network calls: fetch them side by side, then apply the per-source and tier-3 caps in source order
    # so the result is the same as a sequential run.
    with ThreadPoolExecutor(min(8, max(1, len(sources)))) as pool:
        looked = list(pool.map(look, sources))
    for src, (res, exc) in zip(sources, looked):
        if exc is not None:
            print(f"[ingest] {src.id}: ERROR {exc}")
            health[src.id] = {"via": None, "found": 0, "kept": 0, "error": str(exc)}
            continue
        found, how = res
        n = len(found)
        found.sort(key=lambda e: e.published_at, reverse=True)
        kept = found[:per_source]
        if src.tier == 3:
            kept = kept[: max(0, t3_cap - t3)]
            t3 += len(kept)
        capped = [{"title": e.title[:120], "published": e.published_at.isoformat()} for e in found[len(kept):]]  # in the window, over a cap
        found = kept
        print(f"[ingest] {src.id} via {how}: {len(found)} in window" + (f" ({len(capped)} over the cap)" if capped else ""))
        health[src.id] = {"via": how, "found": n, "kept": len(found), "error": None, **({"capped": capped} if capped else {})}
        eps.extend(found)
    return eps
