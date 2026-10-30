"""Podcast links in the X scan: YouTube, Apple Podcasts and Spotify links the followed accounts posted (their own posts
and self-replies), as candidate episodes for the podcast side.

The scanner writes URLs as the X API gives them (`urls`, already expanded). Sigma owns the rest: it follows shorteners
with a HEAD request, keeps podcast links, and looks each one up so `custom-run --picks` can take it. What to do with a
candidate (pick it, ledger its show) is the source-scout procedure's call, not this code's.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import xdaily

SHORTENERS = {"t.co", "bit.ly", "buff.ly", "ow.ly", "lnkd.in", "tinyurl.com", "dlvr.it", "trib.al", "spoti.fi", "apple.co"}
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
MIN_MINUTES = 20  # same floor as the daily people search: shorter is a clip, not an episode


def host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.").removeprefix("m.")


def resolve(url: str, head=None) -> str:
    """Where a shortened link lands (one HEAD request, redirects followed); any other URL as it is."""
    if host(url) not in SHORTENERS:
        return url
    import requests

    try:
        return (head or requests.head)(url, allow_redirects=True, timeout=10).url
    except Exception:
        return url


def classify(url: str) -> tuple[str, str] | None:
    """(kind, id) for a podcast link: ('youtube', video id), ('apple', episode id) or ('spotify', 'episode/<id>' or
    'show/<id>'); None for anything else. Shorts and channel pages are not episodes."""
    u, h = urlparse(url), host(url)
    if h == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif h in ("youtube.com", "music.youtube.com"):
        parts = u.path.strip("/").split("/")
        vid = parse_qs(u.query).get("v", [""])[0] if parts[0] == "watch" else parts[1] if len(parts) > 1 and parts[0] in ("live", "embed") else ""
    elif h == "podcasts.apple.com":
        i = parse_qs(u.query).get("i", [""])[0]
        return ("apple", i) if i.isdigit() else None
    elif h == "open.spotify.com":
        parts = [p for p in u.path.strip("/").split("/") if not p.startswith("intl-")]
        return ("spotify", f"{parts[0]}/{parts[1]}") if len(parts) > 1 and parts[0] in ("episode", "show") else None
    else:
        return None
    return ("youtube", vid) if YT_ID.match(vid) else None


def found_links(d: str, head=None) -> dict[tuple[str, str], dict]:
    """{(kind, id): {url, found_via: [{handle, post_id, at}]}} from the day's posts (followed accounts and their
    self-replies; the scan contract already drops replies to others)."""
    out: dict[tuple[str, str], dict] = {}
    for p in xdaily.read_jsonl(xdaily.scan_dir(d) / "posts.jsonl"):
        urls = list(p.get("urls") or []) + re.findall(r"https?://t\.co/\w+", p.get("text", ""))
        for raw in dict.fromkeys(urls):
            url = resolve(raw, head)
            if not (key := classify(url)):
                continue
            hit = out.setdefault(key, {"url": url, "found_via": []})
            if not any(v["post_id"] == p["id"] for v in hit["found_via"]):
                hit["found_via"].append({"handle": p["handle"], "post_id": p["id"], "at": p["created_at"]})
    return out


def youtube_meta(vid: str) -> dict | None:
    from .ingest import _yt_json

    info = _yt_json([f"https://www.youtube.com/watch?v={vid}"])
    return info[0] if info else None


def apple_meta(i: str, get=None) -> dict | None:
    import requests

    r = (get or requests.get)("https://itunes.apple.com/lookup", params={"id": i, "entity": "podcastEpisode"}, timeout=30)
    rows = [x for x in r.json().get("results", []) if x.get("wrapperType") == "podcastEpisode"] if r.ok else []
    return rows[0] if rows else None


def known_channels(sources_path: Path) -> tuple[set[str], set[str]]:
    from .config import load_sources

    srcs = load_sources(sources_path)[0]
    ids = {s.youtube_channel_id for s in srcs if s.youtube_channel_id}
    names = {n.lower() for s in srcs for n in [s.name, *s.aliases]}
    return ids, names


def candidates(d: str, sources_path: Path, runs: Path, yt=youtube_meta, apple=apple_meta, head=None) -> list[dict]:
    """The day's podcast links as `find --json` candidates, plus `found_via`, `show_followed` and `channel_id`.
    A link that cannot be looked up, or a video under MIN_MINUTES, is kept with `pickable: false` and the reason."""
    from .custom import mark_transcribed

    ids, names = known_channels(sources_path)
    out = []
    for (kind, key), hit in found_links(d, head).items():
        c = {"episode_id": "", "title": "", "show": "", "published": "", "url": hit["url"], "audio_url": None,
             "youtube_id": None, "feed_url": None, "description": "", "duration": None, "minutes": None, "people": [],
             "queries": [], "via": [f"x:{kind}"], "role": None, "transcribed": None, "found_via": hit["found_via"],
             "channel_id": None, "show_followed": False, "pickable": False, "why_not": ""}
        if kind == "youtube":
            m = yt(key)
            if m:
                ts = m.get("release_timestamp") or m.get("timestamp")
                pub = datetime.fromtimestamp(ts, timezone.utc) if ts else (
                    datetime.strptime(m["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc) if m.get("upload_date") else None)
                c.update(episode_id=f"yt:{key}", youtube_id=key, title=m.get("title", ""), show=m.get("channel") or m.get("uploader") or "",
                         channel_id=m.get("channel_id"), published=pub.isoformat() if pub else "",
                         description=(m.get("description") or "")[:2000], duration=m.get("duration"))
        elif kind == "apple":
            m = apple(key)
            if m:
                c.update(episode_id=f"apple:{key}", title=m.get("trackName", ""), show=m.get("collectionName", ""),
                         published=m.get("releaseDate", ""), audio_url=m.get("episodeUrl"), feed_url=m.get("feedUrl"),
                         description=(m.get("description") or "")[:2000],
                         duration=round(m["trackTimeMillis"] / 1000) if m.get("trackTimeMillis") else None)
        if c["duration"]:
            c["minutes"] = round(c["duration"] / 60)
        c["show_followed"] = bool(c["channel_id"] and c["channel_id"] in ids) or c["show"].lower() in names
        c["why_not"] = ("spotify links cannot be looked up; find the episode on Apple or YouTube" if kind == "spotify"
                        else "lookup failed" if not c["title"]
                        else f"under {MIN_MINUTES} min (a clip)" if (c["minutes"] or 0) < MIN_MINUTES else "")
        c["pickable"] = not c["why_not"]
        out.append(c)
    mark_transcribed([c for c in out if c["episode_id"]], runs)
    return sorted(out, key=lambda c: (not c["pickable"], -len(c["found_via"]), c["published"]), reverse=False)


def links_cmd(args) -> None:
    from .paths import data_root

    d = args.date
    if not (xdaily.scan_dir(d) / "manifest.json").exists():
        raise SystemExit(f"[x] no scan for {d} in {xdaily.scan_dir(d)}")
    data = data_root()
    cands = candidates(d, data / "sources.yaml", data / "runs")
    out = xdaily.day_dir(d) / "links.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cands, indent=1, ensure_ascii=False) + "\n")
    for c in cands:
        who = ", ".join(f"@{v['handle']}" for v in c["found_via"])
        tag = "followed" if c["show_followed"] else "NEW SHOW"
        state = "pick" if c["pickable"] else f"skip: {c['why_not']}"
        done = f" [transcribed in {c['transcribed']['run']}]" if c["transcribed"] else ""
        print(f"[x] {c['published'][:10] or '?':10} {c['minutes'] or '?':>3} min  {tag:8}  {(c['show'] or '?')[:26]:26} | "
              f"{(c['title'] or c['url'])[:70]} | {who} | {state}{done}")
    print(f"[x] {len(cands)} podcast links, {sum(c['pickable'] for c in cands)} pickable -> {out}\n"
          f"    pickable ones go straight to `sigma custom-run <name> --picks <file>`; new shows go to the source ledger (source-scout)")
