"""Resolve a clickable listen/watch page per episode (free: iTunes Search/Lookup, YouTube ids). Never audio or tracking."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import date
from html import unescape
from difflib import SequenceMatcher
from pathlib import Path

from .manifest import update as update_manifest

AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac", ".mp4a")
TRACKING = ("podtrac.com", "chrt.fm", "pdst.fm", "pscrb.fm", "swap.fm", "byspotify.com", "traffic.megaphone.fm",
            "traffic.libsyn.com", "dcs.megaphone.fm", "op3.dev", "podscribe", "claritaspod", "arttrk.com", "pfx.vpixl.com",
            "mgln.ai", "rss.art19.com/episodes", "media.blubrry.com", "injector.simplecastaudio.com", "cdn.simplecast.com/audio",
            "anchor.fm/s/", "cloudfront.net", "buzzsprout.com/rss", "redirect.mp3", "audioboom.com/posts/.*\\.mp3")
PREFERRED = ("youtube.com/watch", "youtu.be/", "open.spotify.com/episode", "podcasts.apple.com/")
UA = {"User-Agent": "wire/0.1 (+https://github.com/d3ming/wire)"}


def bad_url(url: str | None) -> str | None:
    """Reason the URL can't be a listen link, or None if it's fine."""
    if not url or not re.match(r"^https?://", url):
        return "not an http(s) URL"
    low = url.lower()
    path = urllib.parse.urlparse(low).path
    if path.endswith(AUDIO_EXT) or ".mp3" in low:
        return "audio file"
    for t in TRACKING:
        if re.search(t, low):
            return f"tracking/CDN host ({t})"
    return None



def similar(a: str, b: str, min_words: int = 2) -> float:
    """0..1 title likeness. One normalised text inside the other counts as 1.0 only when it is a real phrase (min_words words,
    8+ letters): \"ai\" inside a long title is no match."""
    a2, b2 = " ".join(re.sub(r"[^a-z0-9]+", " ", a.lower()).split()), " ".join(re.sub(r"[^a-z0-9]+", " ", b.lower()).split())
    short = min(a2, b2, key=len)
    if short and (a2 in b2 or b2 in a2) and len(short.split()) >= min_words and len(short) >= 8:
        return 1.0
    return SequenceMatcher(None, a2, b2).ratio()


def _text(url: str, timeout: float = 15, data: bytes | None = None) -> str:
    hdr = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdr), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


YT_ID = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/live/)([A-Za-z0-9_-]{11})")


def yt_id(url: str | None) -> str | None:
    m = YT_ID.search(urllib.parse.unquote(url or ""))
    return m.group(1) if m else None


_SHOW_FILLER = {"the", "show", "podcast"}
_CLIP = re.compile(r"#shorts?\b|\bshorts?\b|\bclips?\b|\bhighlights?\b|\btrailer\b", re.I)
_NAME_STOP = {"the", "a", "an", "and", "or", "of", "on", "in", "at", "to", "for", "how", "why", "what", "when", "who", "is", "are",
              "new", "inside", "from", "with", "this", "that", "full", "episode", "interview", "part", "live", "special",
              "wall", "street", "silicon", "valley", "york", "white", "house", "capitol", "hill", "bay", "area"}
_GENERIC = _NAME_STOP | {"about", "billion", "million", "trillion", "still", "year", "years", "says", "said", "just", "next", "will",
                         "your", "their", "into", "over", "more", "most", "than", "talks", "founder", "chief", "founders", "future"}


def _show_core(name: str) -> str:
    return " ".join(w for w in re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split() if w not in _SHOW_FILLER)


def _channel_matches_show(show: str, channel: str) -> bool:
    """Channel is the show's: fuzzy match, or one name is a short form of the other once 'the'/'show'/'podcast' are dropped."""
    if not show or not channel:
        return False
    if similar(show, channel) >= 0.5:
        return True
    a, b = _show_core(show), _show_core(channel)
    return len(min(a, b, key=len)) >= 3 and (a == b or a.startswith(b + " ") or b.startswith(a + " "))


def _name_pairs(title: str) -> set[str]:
    """Adjacent capitalised words ("Andy Jassy"), skipping pairs that include a stopword like 'The' or 'How'."""
    pairs = set()
    for run in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", title):
        words = run.split()
        pairs |= {f"{x} {y}".lower() for x, y in zip(words, words[1:]) if x.lower() not in _NAME_STOP and y.lower() not in _NAME_STOP}
    return pairs


def _distinctive(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", title.lower()) if w not in _GENERIC}


def _days_apart(a: str | None, b: str | None) -> int | None:
    try:
        return abs((date.fromisoformat(str(a)[:10]) - date.fromisoformat(str(b)[:10])).days)
    except ValueError:
        return None


def _secs(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "NA") and float(v) > 0 else None
    except (TypeError, ValueError):
        return None


def durations_agree(a, b) -> bool | None:
    """Two lengths in seconds within 5% (or 60 s, whichever is more); None when either is unknown."""
    x, y = _secs(a), _secs(b)
    return None if x is None or y is None else abs(x - y) <= max(60.0, 0.05 * x)


def shared_segments(a: str, b: str) -> set[str]:
    """Topic segments two titles have in common. Shows such as TBPN title an episode with a comma list of topics ("Samsung
    Controversy, IGTV | guests") and retitle the video with a different lead item but keep some of the same topics."""
    def segs(t: str) -> set[str]:
        parts = (" ".join(re.sub(r"[^a-z0-9&' ]+", " ", p.lower()).split()) for p in re.split(r"[,|;:\u2014\u2013]|\s-\s", t))
        return {p for p in parts if len(re.sub(r"[^a-z0-9]", "", p)) >= 4}
    return segs(a) & segs(b)


def yt_matches(ep: dict, vtitle: str, channel: str = "", published: str | None = None, max_days: int = 4,
               duration=None, own_channel: bool = False) -> bool:
    """Strict: title close (or a guest named in the title, from the show's channel) and, if known, date within max_days.
    Third rule, only with BOTH the show's channel and a known date within max_days: the titles share a person-like name
    ("Andy Jassy") or 4+ distinctive words, the titles are at least half alike, and the video is not a clip/short. YouTube retitles episodes, so similarity alone misses real matches.
    Fourth rule, same conditions with a date within 2 days: the titles share two or more whole topic segments (shared_segments), however different the rest.
    Fifth rule (a title can differ): the video is on the show's own channel (own_channel: it came from that
    channel's uploads or streams; or the channel name matches the show), was published within 1 day of the episode, is no clip,
    and has the episode's length within 5% or 60 s (durations_agree). With either length unknown the rule does not apply, so
    another same-day video of the channel never passes on the channel alone."""
    title, show = ep.get("title", ""), ep.get("show") or ep.get("source") or ""
    if _CLIP.search(vtitle) and not _CLIP.search(title):  # a clip or short is not the episode
        return False
    guests = [g["name"] if isinstance(g, dict) else str(g) for g in ep.get("guests") or []
              if not (isinstance(g, dict) and "host" in (g.get("role") or "").lower())]
    guests = [g for g in guests if g and len(g.split()) >= 2]
    chan_ok = bool(channel) and similar(show, channel) >= 0.5
    ok = similar(title, vtitle, 3) >= 0.75 or (chan_ok and any(g.lower() in vtitle.lower() for g in guests))
    gap = _days_apart(published, ep.get("published")) if published and ep.get("published") else None
    if ok:
        return gap is None or gap <= max_days
    if gap is not None and gap <= 1 and (own_channel or _channel_matches_show(show, channel)) and not _CLIP.search(vtitle) \
            and durations_agree(ep.get("duration"), duration):
        return True
    if gap is not None and gap <= max_days and _channel_matches_show(show, channel) and not _CLIP.search(vtitle):
        if gap <= 2 and len(shared_segments(title, vtitle)) >= 2:
            return True
        if similar(title, vtitle, 3) >= 0.5:
            return bool(_name_pairs(title) & _name_pairs(vtitle)) or len(_distinctive(title) & _distinctive(vtitle)) >= 4
    return False


def yt_channel_rss(ep: dict, channel_id: str, fetch=_text) -> str | None:
    xml = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)", entry)
        vt = re.search(r"<title>([^<]*)", entry)
        pub = re.search(r"<published>([^<]+)", entry)
        if vid and vt and yt_matches(ep, unescape(vt.group(1)), ep.get("show", ""), pub and pub.group(1)):
            return f"https://www.youtube.com/watch?v={vid.group(1)}"
    return None


def yt_oembed(vid: str, fetch=_text) -> dict | None:
    try:
        return json.loads(fetch(f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={vid}"))
    except Exception:
        return None


def yt_verify(ep: dict, url: str, published: str | None = None, fetch=_text, duration=None, own_channel: bool = False) -> str | None:
    """Agent- or search-supplied URL: keep it only if oEmbed title/channel match the episode."""
    vid = yt_id(url)
    meta = yt_oembed(vid, fetch) if vid else None  # oEmbed has no upload date: only the caller's date for THIS video counts
    if meta and yt_matches(ep, meta.get("title", ""), meta.get("author_name", ""), published, duration=duration, own_channel=own_channel):
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def yt_ddg(ep: dict, fetch=_text) -> str | None:
    """Free DuckDuckGo HTML search; often rate-limited ("anomaly" page), then returns None."""
    guests = " ".join(g["name"] for g in ep.get("guests") or [] if isinstance(g, dict))
    q = f"site:youtube.com {ep.get('show', '')} {guests or ep.get('title', '')}"
    page = fetch("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": q}).encode())
    if "anomaly" in page.lower():
        return None
    seen = []
    for vid in YT_ID.findall(urllib.parse.unquote(page)):
        if vid not in seen:
            seen.append(vid)
    for vid in seen[:5]:
        if (u := yt_verify(ep, f"https://www.youtube.com/watch?v={vid}", fetch=fetch)):
            return u
    return None


_YTDLP = {"fails": 0}


def ytdlp_run(cmd: list[str]) -> str:
    """Run yt-dlp. After three failures in a row (YouTube blocks server IPs) it stops asking for the rest of the process."""
    import subprocess

    if _YTDLP["fails"] >= 3:
        raise RuntimeError("yt-dlp keeps failing (YouTube likely blocks this IP); not asking again")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=True).stdout
    except subprocess.CalledProcessError as exc:
        if "does not have a" in (exc.stderr or ""):  # a channel with no /streams tab: nothing there, not a block
            return ""
        _YTDLP["fails"] += 1
        raise
    except Exception:
        _YTDLP["fails"] += 1
        raise
    _YTDLP["fails"] = 0
    return out


def _guest_names(ep: dict) -> str:
    return " ".join(g["name"] for g in ep.get("guests") or [] if isinstance(g, dict) and "host" not in (g.get("role") or "").lower())


def _yt_pick(ep: dict, out: str, fetch, run, own_channel: bool = False) -> str | None:
    """First yt-dlp result line (id, title, channel, upload_date, duration) that passes yt_verify, with the upload date looked up
    for it. A listing carries no date, and a retitled episode fails the undated check, so a candidate that shares topic segments
    with the episode title (shared_segments), or, on the show's own channel, has the episode's length, also gets its date looked
    up and the full dated check. A candidate whose date cannot be found is only taken on the undated title check."""
    import sys

    for line in out.splitlines():
        vid, vtitle, _, up, dur = (line.split("\t") + ["", "", "", "", ""])[:5]
        vid, url = vid.strip(), f"https://www.youtube.com/watch?v={vid.strip()}"
        if not re.fullmatch(r"[\w-]{11}", vid):
            continue
        undated = yt_verify(ep, url, ep.get("youtube_published"), fetch)
        if not undated and len(shared_segments(ep.get("title", ""), vtitle)) < 2 \
                and not (own_channel and durations_agree(ep.get("duration"), dur)):
            continue
        if not re.fullmatch(r"\d{8}", up.strip()):  # flat listings carry no upload date: look it up for the one candidate
            try:
                up = run([sys.executable, "-m", "yt_dlp", "--skip-download", "--print", "%(upload_date)s", url]).strip().splitlines()[-1]
            except Exception:
                up = ""
        if re.fullmatch(r"\d{8}", up.strip()):
            if (dated := yt_verify(ep, url, f"{up[:4]}-{up[4:6]}-{up[6:8]}", fetch, dur, own_channel)):
                return dated
            continue
        if undated:
            return undated
    return None


YT_LIST = "%(id)s\t%(title)s\t%(channel)s\t%(upload_date)s\t%(duration)s"


def yt_ytsearch(ep: dict, fetch=_text, run=None) -> str | None:
    """Last resort, opt-in (Mac/residential IP; YouTube blocks servers): yt-dlp's ytsearch5, first with the show and the guest
    (or title), then with the title alone (the video may sit on another channel, e.g. a host's own). Results are only accepted
    through yt_verify (oEmbed title/channel match, then the upload date, looked up with a second yt-dlp call)."""
    import sys

    run = run or ytdlp_run
    show, title = ep.get("show") or ep.get("source") or "", ep.get("title", "")
    queries = [f"{show} {_guest_names(ep) or title}".strip(), title]
    for q in dict.fromkeys(q for q in queries if q):
        out = run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "--print", YT_LIST, f"ytsearch5:{q}"])
        if (u := _yt_pick(ep, out, fetch, run)):
            return u
    return None


def channel_base(url: str | None) -> str:
    """Channel address on www.youtube.com without a trailing /videos, /streams or /search ("youtube.com/@x" gets the www)."""
    base = re.sub(r"/(videos|streams|search|featured)/?(\?.*)?$", "", (url or "").strip()).rstrip("/")
    return re.sub(r"^https?://(?:www\.|m\.)?youtube\.com/", "https://www.youtube.com/", base)


def yt_channel_uploads(ep: dict, channel_url: str, fetch=_text, run=None, newest: int = 60) -> str | None:
    """The show's own channel (opt-in, same limits as yt_ytsearch). YouTube's channel RSS only lists the last 15 videos and
    returns 404 today, so ask yt-dlp: the channel's search for the title, then its newest uploads (/videos) and newest live
    streams (/streams: a show such as TBPN publishes there only). Same oEmbed and date checks."""
    import sys
    import urllib.parse

    run = run or ytdlp_run
    base = channel_base(channel_url)
    if not base.startswith("https://www.youtube.com/"):
        return None
    q = urllib.parse.quote_plus(ep.get("title", "")[:100])
    for src, end in ((f"{base}/search?query={q}", 8), (f"{base}/videos", newest), (f"{base}/streams", newest)):
        out = run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end", str(end), "--print", YT_LIST, src])
        if (u := _yt_pick(ep, out, fetch, run, own_channel=True)):
            return u
    return None


YT_URL = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s\"'<>]*v=|live/|shorts/)|youtu\.be/)[\w-]{11}[^\s\"'<>]*")


def yt_show_notes(ep: dict, fetch=_text) -> str | None:
    """YouTube links the publisher put in the feed description/show notes; oEmbed-verified (notes often link other eps)."""
    seen = []
    for u in YT_URL.findall(ep.get("description") or ""):
        if (vid := yt_id(u)) and vid not in seen:
            seen.append(vid)
    for vid in seen[:5]:
        if (u := yt_verify(ep, f"https://www.youtube.com/watch?v={vid}", fetch=fetch)):
            return u
    return None


def youtube(ep: dict, channel_id: str | None = None, fetch=_text, ytsearch: bool = False, run=None,
            channel_url: str | None = None) -> str | None:
    """Order: known id, agent-supplied url, feed show notes, channel RSS, web search, then (ytsearch=True) the show's channel
    through yt-dlp (channel_url, or built from channel_id) and a general yt-dlp search."""
    channel_url = channel_url or (f"https://www.youtube.com/channel/{channel_id}" if channel_id else None)
    if ep.get("youtube_id"):
        return f"https://www.youtube.com/watch?v={ep['youtube_id']}"
    if ep.get("youtube_url") and (u := yt_verify(ep, ep["youtube_url"], ep.get("youtube_published"), fetch)):
        return u
    for step in (lambda: yt_show_notes(ep, fetch), (lambda: yt_channel_rss(ep, channel_id, fetch)) if channel_id else None,
                 lambda: yt_ddg(ep, fetch), (lambda: yt_channel_uploads(ep, channel_url, fetch, run)) if ytsearch and channel_url else None,
                 (lambda: yt_ytsearch(ep, fetch, run)) if ytsearch else None):
        if step:
            try:
                if (u := step()):
                    return u
            except Exception:
                pass
    return None


def _get(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode())


def apple_episode(show: str, title: str, feed: str | None = None, get=_get) -> str | None:
    q = urllib.parse.urlencode({"term": show, "media": "podcast", "entity": "podcast", "limit": 10})
    shows = get(f"https://itunes.apple.com/search?{q}").get("results", [])
    if feed:
        shows.sort(key=lambda r: (r.get("feedUrl", "").rstrip("/") != feed.rstrip("/"), -similar(show, r.get("collectionName", ""))))
    else:
        shows.sort(key=lambda r: -similar(show, r.get("collectionName", "")))
    for s in shows[:3]:
        if not (feed and s.get("feedUrl", "").rstrip("/") == feed.rstrip("/")) and similar(show, s.get("collectionName", "")) < 0.6:
            continue
        eps = get(f"https://itunes.apple.com/lookup?id={s['collectionId']}&entity=podcastEpisode&limit=200").get("results", [])
        best = max((e for e in eps if e.get("wrapperType") == "podcastEpisode"),
                   key=lambda e: similar(title, e.get("trackName", "")), default=None)
        if best and similar(title, best.get("trackName", "")) >= 0.8 and not bad_url(best.get("trackViewUrl")):
            return best["trackViewUrl"].split("&uo=")[0]
    # show search missed (renamed shows): search the episode title directly
    q = urllib.parse.urlencode({"term": title[:100], "media": "podcast", "entity": "podcastEpisode", "limit": 10})
    for e in get(f"https://itunes.apple.com/search?{q}").get("results", []):
        feed_ok = feed and e.get("feedUrl", "").rstrip("/") == feed.rstrip("/")
        if similar(title, e.get("trackName", "")) >= 0.9 and (feed_ok or similar(show, e.get("collectionName", "")) >= 0.5) \
                and not bad_url(e.get("trackViewUrl")):
            return e["trackViewUrl"].split("&uo=")[0]
    return None


def apple_collection_id(url: str | None) -> str | None:
    """Collection id from an Apple show URL (.../id1234567)."""
    m = re.search(r"/id(\d+)", url or "")
    return m.group(1) if m else None


def is_homepage(url: str | None, site: str | None = None) -> bool:
    """True when url is no episode page: empty path (https://theringer.com/) or the show's own site address."""
    if not url:
        return False
    u = urllib.parse.urlparse(url.strip())
    if not u.netloc:
        return False
    host = u.netloc.lower().removeprefix("www.")
    if u.path in ("", "/") and not u.query:
        return True
    if site:
        s = urllib.parse.urlparse(site.strip())
        return host == s.netloc.lower().removeprefix("www.") and u.path.rstrip("/") == s.path.rstrip("/") and u.query == s.query
    return False


def itunes_episodes(collection_id: str, get=_get, cache: dict | None = None) -> list[dict]:
    """Episodes of one Apple collection (free iTunes Lookup, up to 200). Cached per collection in `cache`; a failed
    lookup is cached as empty so one run does not retry it for every episode."""
    if cache is not None and collection_id in cache:
        return cache[collection_id]
    try:
        res = get(f"https://itunes.apple.com/lookup?id={collection_id}&entity=podcastEpisode&limit=200").get("results", [])
    except Exception:
        res = []
    eps = [r for r in res if r.get("wrapperType") == "podcastEpisode"]
    if cache is not None:
        cache[collection_id] = eps
    return eps


_TRACK_HOSTS = ("podtrac", "chartable", "pdst.fm", "chrt.fm", "op3.dev", "pscrb", "swap.fm", "podscribe", "claritaspod", "arttrk")
_NUM_WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}


def audio_key(url: str | None) -> str | None:
    """Comparable form of an enclosure URL: no query, no scheme, and tracking-redirect prefixes (podtrac, chartable, pdst,
    op3...) cut off so the redirect and the publisher's own URL compare equal."""
    if not url:
        return None
    u = url.split("#")[0].split("?")[0].lower()
    u = u.split("://")[-1]  # nested redirect targets ("op3.dev/e/https://host/x.mp3")
    parts = [p for p in u.split("/") if p]
    while parts and any(t in parts[0] for t in _TRACK_HOSTS):
        hosts = [i for i, p in enumerate(parts[1:], 1) if "." in p and not p.endswith(AUDIO_EXT)]
        if not hosts:
            break
        parts = parts[hosts[0]:]
    return "/".join(parts) or None


def strict_similar(a: str, b: str) -> float:
    """Title ratio without similar()'s containment shortcut: "Part 1" and "Part 1 and 2" are not the same."""
    norm = lambda t: " ".join(re.sub(r"[^a-z0-9]+", " ", t.lower()).split())
    a2, b2 = norm(a), norm(b)
    return SequenceMatcher(None, a2, b2).ratio() if a2 and b2 else 0.0


def _numbers(title: str) -> list[str]:
    """Digit and number-word tokens (Part 1 / Part One, Oct 23, #214), sorted."""
    toks = re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
    return sorted(_NUM_WORDS.get(t, t) for t in toks if t.isdigit() or t in _NUM_WORDS)


def _same_episode(e: dict, ident: dict) -> bool:
    """Identity match between an iTunes lookup row and a manifest row: guid hash (= manifest episode id), guid, enclosure."""
    guid = e.get("episodeGuid")
    if guid:
        import hashlib

        if ident.get("episode_id") == "rss:" + hashlib.sha1(guid.encode()).hexdigest()[:16] or ident.get("guid") == guid:
            return True
    ek, mk = audio_key(e.get("episodeUrl")), audio_key(ident.get("audio_url"))
    return bool(ek and mk and ek == mk)


def match_itunes_episode(title: str, published: str | None, eps: list[dict], min_sim: float = 0.9, max_days: int = 2,
                         ident: dict | None = None) -> str | None:
    """Apple episode page for the episode. First by identity (ident = manifest row with episode_id/guid/audio_url against
    the lookup's episodeGuid/episodeUrl). Otherwise the title must match strictly (>= min_sim, no containment), carry the
    same numbers (Part 1 vs 2, dates), and fall within max_days; ties go to the smallest date gap. No match: None."""
    ok = [e for e in eps if not bad_url(e.get("trackViewUrl"))]
    if ident:
        for e in ok:
            if _same_episode(e, ident):
                return e["trackViewUrl"].split("&uo=")[0]
    best, best_key = None, None
    for e in ok:
        gap = _days_apart(published, e.get("releaseDate"))
        name = e.get("trackName", "")
        sim = strict_similar(title, name)
        if gap is None or gap > max_days or sim < min_sim or _numbers(title) != _numbers(name):
            continue
        key = (gap, -sim)
        if best_key is None or key < best_key:
            best, best_key = e, key
    return best["trackViewUrl"].split("&uo=")[0] if best else None


def apple_show_episode(title: str, published: str | None, apple_url: str | None, get=_get, cache: dict | None = None,
                       ident: dict | None = None) -> str | None:
    """Episode page on Apple Podcasts via the show's collection id from show_links.yaml."""
    cid = apple_collection_id(apple_url)
    return match_itunes_episode(title, published, itunes_episodes(cid, get, cache), ident=ident) if cid else None


def episode_urls(episodes: list[dict], shows: dict, manifest: dict | None = None, get=_get) -> list[tuple]:
    """For ranked-digest rows: when `url` is missing, a tracking/audio link or just the show homepage, replace it in place
    with the manifest's listen_url, else the Apple episode page matched through the iTunes lookup. Returns [(rank, old, new)]."""
    cache, changed = {}, []
    for e in episodes:
        row = shows.get((e.get("source") or "").lower(), {})
        url = e.get("url") or ""
        if url and not bad_url(url) and not is_homepage(url, row.get("site")):
            continue
        lu = ((manifest or {}).get(e.get("episode_id"), {}) or {}).get("listen_url")
        if not (lu and not bad_url(lu) and not is_homepage(lu, row.get("site"))):
            ident = {**((manifest or {}).get(e.get("episode_id"), {}) or {}), "episode_id": e.get("episode_id")}
            lu = apple_show_episode(e.get("title", ""), e.get("published"), row.get("apple"), get, cache, ident)
        if lu and lu != url:
            e["url"] = lu
            changed.append((e.get("rank"), url, lu))
    return changed


def resolve(ep: dict, feed: str | None = None, get=_get) -> str | None:
    """Non-YouTube listen page: existing Spotify/Apple page, Apple lookup, then feed episode page."""
    url = ep.get("url")
    if url and not bad_url(url) and any(p in url for p in PREFERRED[:3]):
        return url
    if url and "podcasts.apple.com/" in url and not bad_url(url):
        return url.split("&uo=")[0]
    try:
        apple = apple_episode(ep.get("show") or ep.get("source") or "", ep.get("title", ""), feed, get)
    except Exception:  # network errors fall through to the page link
        apple = None
    if apple:
        return apple
    return url if url and not bad_url(url) else None


SPOTIFY_EPISODE = re.compile(r"open\.spotify\.com/(?:embed/)?episode/([A-Za-z0-9]{22})|spotify:episode:([A-Za-z0-9]{22})")
_SPOTIFY_LISTED = re.compile(r'href="/episode/([A-Za-z0-9]{22})"[^>]*>(.*?)</a>', re.S)


def _spotify_page(url: str, timeout: float = 15) -> str:
    # a bare "Mozilla/5.0" gets Spotify's server-rendered page (same as showlinks._page)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def spotify_listed(show_url: str, fetch=_spotify_page) -> list[tuple[str, str]]:
    """(episode id, title) for the episodes Spotify's public show page lists (the newest few; no API key)."""
    page = fetch(show_url)
    return [(m.group(1), " ".join(unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())) for m in _SPOTIFY_LISTED.finditer(page)]


def spotify_embed(eid: str, fetch=_spotify_page) -> dict:
    """Title and release date of one episode from its public embed page (no API key); {} when unreadable."""
    page = fetch(f"https://open.spotify.com/embed/episode/{eid}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    try:
        ent = json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return {}
    return {"title": ent.get("title") or ent.get("name") or "", "released": (ent.get("releaseDate") or {}).get("isoString", "")}


def spotify_verify(title: str, published: str | None, eid: str, fetch=_spotify_page, max_days: int = 2) -> str | None:
    """Episode URL only when the embed page's title matches strictly (0.9, same numbers) and the release date is within max_days."""
    info = spotify_embed(eid, fetch)
    gap = _days_apart(published, info.get("released"))
    if info and gap is not None and gap <= max_days and strict_similar(title, info["title"]) >= 0.9 \
            and _numbers(title) == _numbers(info["title"]):
        return f"https://open.spotify.com/episode/{eid}"
    return None


def spotify_episode(ep: dict, show_url: str | None = None, fetch=_spotify_page) -> str | None:
    """Spotify episode page, verified: an episode link in the feed's own url/notes, else the newest episodes on the show's
    Spotify page. Spotify has no keyless search, so older episodes get no episode link (callers fall back to the show)."""
    title, published = ep.get("title", ""), ep.get("published")
    cands = []
    for text in (ep.get("url"), ep.get("listen_url"), ep.get("description")):
        cands += [a or b for a, b in SPOTIFY_EPISODE.findall(text or "")]
    if show_url:
        try:
            cands += [eid for eid, t in spotify_listed(show_url, fetch) if strict_similar(title, t) >= 0.8]
        except Exception:
            pass
    for eid in dict.fromkeys(cands):
        try:
            if (u := spotify_verify(title, published, eid, fetch)):
                return u
        except Exception:
            continue
    return None


def apple_episode_link(ep: dict, show_apple: str | None, get=_get, cache: dict | None = None) -> str | None:
    """Apple Podcasts episode page, never the show page: the feed's own Apple episode url (an iTunes-discovered episode has
    one), else the strict iTunes match (guid or enclosure, or near-exact title and date) through the show's collection id."""
    for u in (ep.get("url"), ep.get("listen_url")):
        if u and "podcasts.apple.com/" in u and re.search(r"[?&]i=\d+", u) and not bad_url(u):
            return u.split("&uo=")[0]
    return apple_show_episode(ep.get("title", ""), ep.get("published"), show_apple, get, cache, ep)


def cached_run(run):
    """`run` that answers a repeated yt-dlp command from memory, so one channel's /videos and /streams listings are read once
    per lookup however many of its episodes need a link. A failed call is not remembered."""
    memo: dict[tuple, str] = {}

    def cached(cmd: list[str]) -> str:
        key = tuple(cmd)
        if key not in memo:
            memo[key] = run(cmd)
        return memo[key]

    return cached


def listen_links(rows: list[dict], shows: dict, srcs: dict | None = None, *, get=_get, fetch=_text, ytsearch: bool = True,
                 run=None, spotify_fetch=_spotify_page) -> dict:
    """Per-episode listen links for publishing: {episode_id: {youtube_url, apple_url, spotify_url, spotify_kind}}, only keys
    that were found. `rows` carry title, show/source, published and whatever the manifest knows (youtube_id, url, description,
    guid, audio_url); `shows` is show_links by lower-case name, `srcs` sources.yaml by lower-case name. Every link is strict:
    YouTube needs oEmbed title-or-guest plus date, Apple a guid/enclosure or near-exact title and date, a Spotify episode the
    embed page's title and date. A show link from show_links.yaml stands in for Spotify only (spotify_kind "show").
    Best effort: a network error drops that link, never the others."""
    srcs, cache, out = srcs or {}, {}, {}
    run = cached_run(run or ytdlp_run)
    for ep in rows:
        name = (ep.get("show") or ep.get("source") or "").lower()
        sl, src, res = shows.get(name, {}), srcs.get(name, {}), {}
        # Apple: the show page in show_links.yaml, else the source's itunes_id (an exact collection, no search)
        show_apple = sl.get("apple") or (f"https://podcasts.apple.com/podcast/id{src['itunes_id']}" if src.get("itunes_id") else None)
        steps = {
            "youtube_url": lambda: youtube(ep, src.get("youtube_channel_id"), fetch, ytsearch, run, sl.get("youtube") or src.get("youtube") or None),
            "apple_url": lambda: apple_episode_link(ep, show_apple, get, cache),
        }
        for key, fn in steps.items():
            try:
                if (u := fn()):
                    res[key] = u
            except Exception:
                pass
        try:
            u = spotify_episode(ep, sl.get("spotify"), spotify_fetch)
        except Exception:
            u = None
        if u:
            res["spotify_url"], res["spotify_kind"] = u, "episode"
        elif sl.get("spotify"):
            res["spotify_url"], res["spotify_kind"] = sl["spotify"], "show"
        if res:
            out[ep["episode_id"]] = res
    return out


def transcript_link(row: dict) -> str | None:
    """Hosted transcript for a manifest row: the recorded URL (any host, but never audio), else the YouTube video whose
    captions were used."""
    u = row.get("transcript_url") or ""
    if u.startswith(("http://", "https://")) and not u.lower().split("?")[0].endswith(AUDIO_EXT):
        return u
    if "youtube-captions" in (row.get("transcript_source") or "") and row.get("youtube_id"):
        return f"https://www.youtube.com/watch?v={row['youtube_id']}"
    return None


def transcript_label(url: str) -> str:
    return "YouTube captions" if "youtube.com/" in url or "youtu.be/" in url else "Publisher transcript"


def backfill_transcript_urls(run_dir: Path, sources: Path, parse=None) -> dict:
    """Older manifests did not record where a podcast:transcript came from. Re-read each show's feed, match the episode by
    title and store the transcript link. YouTube-caption rows need nothing (transcript_link derives them)."""
    if parse is None:
        import feedparser
        parse = feedparser.parse
    from .ingest import transcript_links

    man_p = run_dir / "manifest.json"
    rows = [r for r in json.loads(man_p.read_text()).get("episodes", [])
            if r.get("transcript_source") == "podcast:transcript" and not r.get("transcript_url")]
    import yaml
    srcs = {s["id"]: s for s in yaml.safe_load(sources.read_text()).get("sources", []) if s.get("id")}
    feeds, found = {}, {}
    for r in rows:
        src = srcs.get(r.get("source_tag"))
        if not src:
            continue
        try:
            entries = feeds.setdefault(src["rss"], parse(src["rss"]).entries)
        except Exception:
            continue
        best = max(entries, key=lambda e: similar(r["title"], e.get("title", "")), default=None)
        if best and similar(r["title"], best.get("title", "")) >= 0.9 and (links := transcript_links(best)):
            found[r["episode_id"]] = links[0]["url"]

    def apply(m):
        for row in m.get("episodes", []):
            if row["episode_id"] in found:
                row["transcript_url"] = found[row["episode_id"]]

    if found:
        update_manifest(man_p, apply)
    return {"missing": len(rows), "found": len(found)}


def sources_by_name(sources: Path) -> dict:
    import yaml
    data = yaml.safe_load(sources.read_text()) or {}
    return {s["name"].lower(): s for s in data.get("sources", []) if isinstance(s, dict) and s.get("name")}


def fill(run_dir: Path, sources: Path | None = None, get=_get, fetch=_text, ytsearch: bool = False, show_links: Path | None = None) -> dict:
    """Write youtube_url (verified or empty) and listen_url (non-YouTube fallback) into selected.json and the manifest.
    Returns {episode_id: (youtube_url, listen_url)}."""
    sel_p, man_p = run_dir / "selected.json", run_dir / "manifest.json"
    sel = json.loads(sel_p.read_text())
    man = json.loads(man_p.read_text()) if man_p.exists() else {"episodes": []}
    by_id = {e["episode_id"]: e for e in man.get("episodes", [])}
    srcs = sources_by_name(sources) if sources and sources.exists() else {}
    from .showlinks import by_name as show_links_by_name
    shows = show_links_by_name(show_links) if show_links else {}
    out, found, itunes_cache = {}, {}, {}
    for e in sel["episodes"]:
        m = by_id.get(e["episode_id"], {})
        ep = {**m, **e, "youtube_id": e.get("youtube_id") or m.get("youtube_id")}
        if not ep.get("description") and m.get("file") and (run_dir / m["file"]).exists():  # older manifests
            md = re.search(r"## Description\n\n(.*?)(?:\n## |\Z)", (run_dir / m["file"]).read_text(), re.S)
            ep["description"] = md.group(1) if md else ""
        src = srcs.get((e.get("show") or "").lower(), {})
        sl = shows.get((e.get("show") or "").lower(), {})
        yt = youtube(ep, src.get("youtube_channel_id"), fetch, ytsearch, channel_url=sl.get("youtube") or None)
        lu = e.get("listen_url") if e.get("listen_url") and not bad_url(e["listen_url"]) and not yt_id(e["listen_url"]) \
            and not is_homepage(e["listen_url"]) else None
        if not lu and (not ep.get("url") or bad_url(ep["url"]) or is_homepage(ep["url"], sl.get("site"))):
            lu = apple_show_episode(ep.get("title", ""), ep.get("published"), sl.get("apple"), get, itunes_cache,
                                    {**m, "episode_id": e["episode_id"]})
        lu = lu or resolve(ep, src.get("rss"), get)
        if lu and is_homepage(lu, sl.get("site")):  # a show homepage is not an episode link
            lu = None
        if not lu and not yt:  # no episode page anywhere: the show's own Apple page (then site) beats nothing
            lu = sl.get("apple") or sl.get("site") or None
        out[e["episode_id"]] = (yt, lu)
        for d in (e, m) if m else (e,):
            d.pop("youtube_url", None) if not yt else d.__setitem__("youtube_url", yt)
            if lu:
                d["listen_url"] = lu
        if m:
            found[e["episode_id"]] = (yt, lu)
    sel_p.write_text(json.dumps(sel, indent=1, ensure_ascii=False) + "\n")
    if man_p.exists():
        def apply(manifest):  # only the link fields, onto the fresh manifest (transcribe may be writing it)
            for row in manifest.get("episodes", []):
                if (hit := found.get(row["episode_id"])):
                    yt, lu = hit
                    row.pop("youtube_url", None) if not yt else row.__setitem__("youtube_url", yt)
                    if lu:
                        row["listen_url"] = lu

        update_manifest(man_p, apply)
    return out
