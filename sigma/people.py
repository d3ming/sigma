from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import yaml

from .feedcache import image_url
from .ingest import Episode, _yt_json, canonical_id, in_window, parse_date
from .config import check
from .transcribe import title_match

PEOPLE_DEFAULTS = {"preferred_source": "itunes", "fallback": [], "transcripts": ["podcast_transcript", "whisper"]}

CLIP = re.compile(r"#shorts|\bclips?\b|\breacts?\b|\breaction\b|\bhighlights?\b|\bexplained\b|\bAI voice\b", re.I)
OFF_GENRES = {"sports", "fiction", "kids & family", "religion & spirituality", "comedy", "leisure", "true crime",
              "tv & film", "music", "fantasy sports", "football", "basketball", "baseball", "hockey", "soccer"}
OFF_TOPIC = re.compile(r"\b(sports?|radio show|football|basketball|baseball|hockey|soccer|nfl|nba|mlb|nhl|ncaa|fcs|playoffs?|"
                       r"quarterback|touchdown|tip-?off|recruiting|fantasy|vs\.? [A-Z]{2,4}\b)", re.I)
WINDOW = [(1, "EgQIAhAB"), (7, "EgQIAxAB"), (31, "EgQIBBAB"), (366, "EgQIBRAB")]


@dataclass
class Person:
    name: str
    role: str
    priority: str
    aliases: list[str] = field(default_factory=list)
    preferred_source: str = "itunes"
    fallback: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)  # for common names: one must appear in title/description/show

    @property
    def order(self) -> list[str]:
        return list(dict.fromkeys([self.preferred_source, *self.fallback]))

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    @property
    def tag(self) -> str:
        return f"person:{self.name}"


def load_people(path: str | Path) -> list[Person]:
    data = yaml.safe_load(Path(path).read_text())
    defaults = {**PEOPLE_DEFAULTS, **data.get("defaults", {})}
    people = [Person(**{**defaults, **p}) for p in data["people"]]
    for p in people:
        check(p.name, vars(p))
        if p.priority not in ("core", "watch"):
            raise ValueError(f"{p.name}: priority must be core or watch")
    if len({p.name for p in people}) != len(people):
        raise ValueError("duplicate person name")
    return people


def mentions(person: Person, *texts: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    hay = f" {norm(' '.join(t or '' for t in texts))} "
    return any(f" {norm(n)} " in hay for n in person.names)


def genres(r: dict) -> set[str]:
    g = r.get("genres") or []
    names = [x.get("name", "") if isinstance(x, dict) else str(x) for x in g] + [r.get("primaryGenreName") or ""]
    return {n.lower() for n in names if n}


def on_topic(person: Person, title: str, description: str, show: str, genre_names: set[str] = frozenset()) -> bool:
    """Reject same-name hits from sports, fiction, etc. and, when `context` is set, hits that never mention it."""
    if genre_names & OFF_GENRES or OFF_TOPIC.search(f"{title} {show}"):
        return False
    if person.context:
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
        hay = f" {norm(title)} {norm(description)} {norm(show)} "
        return any(f" {norm(c).strip()} " in hay for c in person.context)
    return True


def is_clip(title: str, channel: str, description: str, duration: float | None, min_minutes: int) -> bool:
    if (duration or 0) < min_minutes * 60:
        return True
    return bool(CLIP.search(title) or CLIP.search(channel or "") or re.search(r"full (video|episode|interview):\s*http", description or "", re.I))


def _ep(person: Person, **kw) -> Episode:
    return Episode(source_id=person.tag, source_name=kw.pop("show"), tier=2, **kw)


def youtube_candidates(person: Person, min_minutes: int, rows: list[dict]) -> list[dict]:
    return [r for r in rows if mentions(person, r.get("title"), r.get("description"))
            and on_topic(person, r.get("title", ""), r.get("description", ""), r.get("channel", ""))
            and not is_clip(r.get("title", ""), r.get("channel", ""), r.get("description", ""), r.get("duration"), min_minutes)]


def _youtube_rows(term: str, days: int) -> list[dict]:
    sp = next(code for d, code in WINDOW if days <= d)
    return _yt_json(["--flat-playlist", "-I", "1:20", f"https://www.youtube.com/results?search_query={quote_plus(term)}&sp={sp}"])


def _youtube_episodes(rows: list[dict], tag: str, now: datetime, days: int, limit: int) -> list[Episode]:
    """Look each search row up for its release time and keep those inside the window."""
    out = []
    for r in rows[:limit * 2]:
        info = (_yt_json([f"https://www.youtube.com/watch?v={r['id']}"]) or [None])[0]
        if not info:
            continue
        ts = info.get("release_timestamp") or info.get("timestamp")
        dt = datetime.fromtimestamp(ts, timezone.utc) if ts else None
        if not dt or not in_window(dt, now, days):
            continue
        out.append(Episode(id=canonical_id(None, r["id"], None), source_id=tag, source_name=info.get("channel") or r.get("channel", ""),
                           tier=2, title=info.get("title", ""), url=f"https://www.youtube.com/watch?v={r['id']}", published_at=dt,
                           youtube_id=r["id"], description=(info.get("description") or "")[:2000],
                           duration=int(info["duration"]) if info.get("duration") else None))
        if len(out) >= limit:
            break
    return out


def from_youtube_search(person: Person, now: datetime, days: int, limit: int = 3, min_minutes: int = 20) -> list[Episode]:
    rows = youtube_candidates(person, min_minutes, _youtube_rows(person.name + " interview", days))
    return _youtube_episodes(rows, person.tag, now, days, limit)


def mentions_all(query: str, *texts: str) -> bool:
    """Every word of a free-text query appears (as a whole word) in the texts."""
    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    hay = f" {norm(' '.join(t or '' for t in texts))} "
    return all(f" {w} " in hay for w in norm(query).split())


def from_youtube_query(query: str, now: datetime, days: int, limit: int = 5, min_minutes: int = 20) -> list[Episode]:
    """Free-text YouTube search (not tied to a person): full-length videos whose title or description has every query word."""
    generic = Person(name=query, role="", priority="watch")
    rows = [r for r in _youtube_rows(query + " interview", days)
            if mentions_all(query, r.get("title"), r.get("description"), r.get("channel"))
            and on_topic(generic, r.get("title", ""), r.get("description", ""), r.get("channel", ""))
            and not is_clip(r.get("title", ""), r.get("channel", ""), r.get("description", ""), r.get("duration"), min_minutes)]
    return _youtube_episodes(rows, f"query:{query}", now, days, limit)


def parse_itunes(person: Person, results: list[dict], now: datetime, days: int, min_minutes: int = 20) -> list[Episode]:
    show_art = {r["collectionId"]: art for r in results
                if r.get("wrapperType") == "track" and r.get("kind") == "podcast" and r.get("collectionId")
                and (art := image_url(r.get("artworkUrl600") or r.get("artworkUrl100")))}
    out = []
    for r in results:
        dt = parse_date(r.get("releaseDate"))
        if not dt or not in_window(dt, now, days) or (r.get("trackTimeMillis") or 0) < min_minutes * 60000:
            continue
        if not mentions(person, r.get("trackName"), r.get("description")):
            continue
        if not on_topic(person, r.get("trackName", ""), r.get("description", ""), r.get("collectionName", ""), genres(r)):
            continue
        out.append(_ep(person, id=canonical_id(r.get("episodeGuid"), None, r.get("trackViewUrl")), show=r.get("collectionName", ""),
                       title=r.get("trackName", ""), url=r.get("trackViewUrl") or r.get("episodeUrl", ""), published_at=dt,
                       audio_url=r.get("episodeUrl"), feed_url=r.get("feedUrl"), description=(r.get("description") or "")[:2000],
                       duration=round(r["trackTimeMillis"] / 1000) if r.get("trackTimeMillis") else None,
                       image_url=image_url(r.get("artworkUrl600") or r.get("artworkUrl160")),
                       show_image_url=show_art.get(r.get("collectionId")) or image_url(r.get("collectionArtworkUrl600"))))
    return out


ITUNES_RETRIES, ITUNES_BACKOFF = 4, 2.0


def itunes_search(term: str, get=None, sleep=None) -> list[dict]:
    """iTunes Search allows ~20 requests/min; searches run a few at a time, and 403/429/5xx wait (Retry-After, else doubling) and retry."""
    import time

    import requests

    get, sleep = get or requests.get, sleep or time.sleep
    for attempt in range(ITUNES_RETRIES):
        r = get("https://itunes.apple.com/search", timeout=30,
                params={"term": term, "media": "podcast", "entity": "podcastEpisode", "limit": 50})
        if r.status_code in (403, 429) or r.status_code >= 500:
            if attempt + 1 < ITUNES_RETRIES:
                try:
                    wait = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    wait = ITUNES_BACKOFF * 2 ** attempt
                sleep(min(wait, 30))
                continue
        r.raise_for_status()
        return r.json().get("results", [])
    raise AssertionError("unreachable")


def attach_collection_art(episodes: list[Episode], results: list[dict], get=None) -> list[Episode]:
    from .apple_art import collection_image

    collections = {canonical_id(row.get("episodeGuid"), None, row.get("trackViewUrl")): row.get("collectionId")
                   for row in results}
    artwork = {}
    for episode in episodes:
        collection = collections.get(episode.id)
        if episode.show_image_url or not isinstance(collection, int) or collection <= 0:
            continue
        if collection not in artwork:
            artwork[collection] = collection_image(collection, get)
        episode.show_image_url = artwork[collection]
    return episodes


def from_itunes(person: Person, now: datetime, days: int, get=None, sleep=None, min_minutes: int = 20) -> list[Episode]:
    rows = itunes_search(person.name, get, sleep)
    return attach_collection_art(parse_itunes(person, rows, now, days, min_minutes), rows, get)


def from_itunes_query(query: str, now: datetime, days: int, get=None, sleep=None, min_minutes: int = 20) -> list[Episode]:
    """Free-text podcast-episode search (a company, a topic): episodes in the window and long enough, whose title,
    description or show has every query word. Same off-topic filter as a person search."""
    generic = Person(name=query, role="", priority="watch")
    rows = itunes_search(query, get, sleep)
    out = []
    for r in rows:
        dt = parse_date(r.get("releaseDate"))
        if not dt or not in_window(dt, now, days) or (r.get("trackTimeMillis") or 0) < min_minutes * 60000:
            continue
        if not mentions_all(query, r.get("trackName"), r.get("description"), r.get("collectionName")):
            continue
        if not on_topic(generic, r.get("trackName", ""), r.get("description", ""), r.get("collectionName", ""), genres(r)):
            continue
        out.append(Episode(id=canonical_id(r.get("episodeGuid"), None, r.get("trackViewUrl")), source_id=f"query:{query}",
                           source_name=r.get("collectionName", ""), tier=2, title=r.get("trackName", ""),
                           url=r.get("trackViewUrl") or r.get("episodeUrl", ""), published_at=dt, audio_url=r.get("episodeUrl"),
                           feed_url=r.get("feedUrl"), description=(r.get("description") or "")[:2000],
                           duration=round(r["trackTimeMillis"] / 1000) if r.get("trackTimeMillis") else None,
                       image_url=image_url(r.get("artworkUrl600") or r.get("artworkUrl160")),
                       show_image_url=image_url(r.get("collectionArtworkUrl600"))))
    return attach_collection_art(out, rows, get)


def dedupe(channel_eps: list[Episode], person_eps: list[Episode], threshold: float = 0.8) -> list[Episode]:
    kept, ids = [], {e.id for e in channel_eps}
    titles = [e.title for e in channel_eps]
    for e in person_eps:
        dup = next((k for k in kept if k.id == e.id or title_match(k.title, e.title) >= threshold), None)
        if dup and dup.source_id != e.source_id and e.source_id not in dup.source_id.split(","):
            dup.source_id += "," + e.source_id
        if dup or e.id in ids or any(title_match(t, e.title) >= threshold for t in titles):
            continue
        kept.append(e)
        ids.add(e.id)
    return kept


def _norm_show(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _norm_feed(u: str | None) -> str:
    return re.sub(r"^https?://(www\.)?", "", (u or "").strip().lower()).rstrip("/")


def source_for(name: str | None, sources) -> object | None:
    """The sources.yaml show a publisher's show name refers to. Apple and feeds often add a host or network to the name
    ("Invest Like the Best with Patrick O'Shaughnessy", "CNBC Squawk on the Street"), so a whole-word containment
    either way also matches, for names long enough (8+ characters) not to collide."""
    n = _norm_show(name)
    if not n:
        return None
    for s in sources:
        if n in {_norm_show(x) for x in [s.name, *s.aliases]}:
            return s
    for s in sources:
        k = _norm_show(s.name)
        short, long_ = sorted((k, n), key=len)
        if len(short) >= 8 and f" {short} " in f" {long_} ":
            return s
    for s in sources:  # spacing differs: "BG2Pod with Brad Gerstner" is the show listed as "BG2 Pod"
        k, head = _norm_show(s.name).replace(" ", ""), ""
        for word in n.split(" "):
            head += word
            if len(head) >= len(k):
                break
        if len(k) >= 5 and head == k:
            return s
    return None


def apply_source_tiers(eps: list[Episode], sources, default: int = 2) -> list[Episode]:
    """Person-search hits take the tier and style of their show in sources.yaml (feed URL, Apple id or name), else `default`.
    A matched hit also takes the show's sources.yaml name, so one show is never split across two names."""
    by_feed = {_norm_feed(s.rss): s for s in sources if s.rss}
    by_id = {str(s.itunes_id): s for s in sources if getattr(s, "itunes_id", None)}
    for e in eps:
        m = re.search(r"/id(\d+)", e.url or "")
        src = (by_feed.get(_norm_feed(e.feed_url)) if e.feed_url else None) \
            or (by_id.get(m.group(1)) if m else None) or source_for(e.source_name, sources)
        e.tier = src.tier if src else default
        e.style = src.style if src else "interview"
        if src:
            e.source_name = src.name
    return eps


FINDERS = {"itunes": from_itunes, "ytdlp": from_youtube_search}


def feed_transcripts(eps: list[Episode], parse=None) -> int:
    """Attach the feed's transcript tags to iTunes hits. Feeds are loaded side by side through feedcache (a feed already
    fetched by this run's channel discovery is a 304 or a body-hash hit, not a second parse). `parse(url).entries` overrides."""
    from concurrent.futures import ThreadPoolExecutor

    from .ingest import transcript_links

    if parse is None:
        from .feedcache import load_feed

        entries_of = lambda url: load_feed(url)["entries"]
    else:
        entries_of = lambda url: parse(url).entries
    urls = list(dict.fromkeys(e.feed_url for e in eps if e.feed_url and not e.transcript_urls))

    def load(url):
        try:
            return {canonical_id(x.get("id") or x.get("guid"), None, x.get("link")): x for x in entries_of(url)}
        except Exception:
            return {}

    with ThreadPoolExecutor(min(8, max(1, len(urls)))) as pool:
        feeds = dict(zip(urls, pool.map(load, urls)))
    found = 0
    for e in eps:
        if not e.feed_url or e.transcript_urls:
            continue
        entry = feeds[e.feed_url].get(e.id)
        if entry is not None:
            e.transcript_urls = transcript_links(entry) or None
            found += bool(e.transcript_urls)
    return found


def discover_people(people: list[Person], now: datetime, days: int, channel_eps: list[Episode], per_person: int = 3,
                    only: tuple[str, ...] | None = None, workers: int = 3) -> tuple[list[Episode], dict]:
    """Searches run `workers` at a time (iTunes allows ~20/min); results are merged in the original person/source order."""
    from concurrent.futures import ThreadPoolExecutor

    found, counts, errors, skipped = [], {}, [], set()
    jobs = [(p, src) for p in sorted(people, key=lambda p: p.priority != "core") for src in only or p.order]

    def search(job):
        p, src = job
        try:
            return FINDERS[src](p, now, days), None
        except Exception as exc:
            return None, exc

    with ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as pool:
        results = list(pool.map(search, jobs))
    for (p, src), (eps, exc) in zip(jobs, results):
        if isinstance(exc, LookupError):
            skipped.add(f"{src}: {exc}")
            continue
        if exc is not None:
            errors.append(f"{p.name}/{src}: {type(exc).__name__}")
            continue
        found += [replace(e, via=src, methods=p.transcripts or None) for e in eps[:per_person]]
        print(f"[people] {p.name}/{src}: {len(eps)}")
    kept = dedupe(channel_eps, found)
    for e in kept:
        counts[e.via] = counts.get(e.via, 0) + 1
    tags = feed_transcripts(kept) if not only else 0
    return kept, {"per_source": counts, "candidates": len(found), "feed_transcript_tags": tags, "errors": errors,
                  "skipped_sources": sorted(skipped) + ["podcast-index: needs an API key"]}
