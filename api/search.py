"""GET /api/search?q=...: search what was said in Sigma's episodes. A Vercel Python function; standard library only.

The index (built by `sigma search-index`) lives in a PRIVATE Vercel Blob store. This function downloads it with
SEARCH_READ_WRITE_TOKEN (the sigma-search store's), keeps a copy in /tmp and answers from that copy. It returns short snippets only (at most 40 words
each, at most 2 per episode, at most 20 results); the full transcripts are never published.

For local runs, SIGMA_SEARCH_INDEX_FILE points at an index file and skips Blob.

Response (JSON; the contract the Find page and other agents read, also stated for agents in sigma/site.py find_md):
    200 {"q", "results": [{"show", "title", "date", "timestamp" (seconds), "time" ("1:02:05"), "snippet" (matches in [[ ]]), "link"}]}
Internal links are root-relative paths such as `/episodes/example.html`; clients resolve them against the same origin as this API URL.
    400 {"error"} for an empty query or one over MAX_QUERY_CHARS; 503 {"error"} when the index cannot be read (the Find page
    still filters episodes). Words are ANDed, a "quoted phrase" stays a phrase, and a word in capitals (NVDA, $NVDA) also matches
    the company's names. A show leaves the index with `no_search: true` in sources.yaml (sigma/searchindex.py).

Dependencies: Vercel installs a function's dependencies from the nearest dependency file above it, and the root pyproject.toml
(feedparser, yt-dlp, ...) would otherwise go into the function. api/requirements.txt is empty on purpose so it is the nearest one,
and vercel.json `excludeFiles` leaves the repository's other files out of the bundle. Keep both when changing this function
(checked with `vercel build`: 2,049 vendored files before, 644 after, all Vercel's own).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit, urlunsplit

PATHNAME = "sigma-search/index.sqlite"  # the Blob pathname sigma/searchindex.py uploads to
CACHE = "/tmp/sigma-search-index.sqlite"
CACHE_SECONDS = 3600  # the index is rebuilt daily; a warm function re-downloads at most once an hour
MAX_QUERY_CHARS = 100
MAX_TERMS = 8
MAX_RESULTS = 20
PER_EPISODE = 2
MAX_WORDS = 40
CANDIDATES = 400


class Unavailable(RuntimeError):
    pass


def fts_query(q: str, names=None) -> str | None:
    """The library's rule (sigma/library.py fts_query): "quoted phrases" stay phrases, other words are ANDed. None if no words.
    A word typed as a ticker (NVDA or $NVDA, in capitals) also matches the company's names: names(ticker) -> list."""
    out = []
    for m in re.finditer(r'"([^"]+)"|(\$?)([\w][\w.\-]*)', q):
        term = (m.group(1) or m.group(3)).replace('"', " ").strip()
        if not term:
            continue
        alts = [term]
        if names and not m.group(1) and (m.group(2) or term.isupper()):
            alts += [n.replace('"', " ").strip() for n in names(term.upper())]
        out.append(f'"{term}"' if len(alts) == 1 else "(" + " OR ".join(f'"{a}"' for a in alts) + ")")
    return " AND ".join(out[:MAX_TERMS]) or None  # explicit: FTS5 reads a bare space after a (group) as a syntax error


def index_path() -> str:
    """The local index file: the override for local runs, else the cached Blob download (refreshed hourly)."""
    local = os.environ.get("SIGMA_SEARCH_INDEX_FILE")
    if local:
        return local
    try:
        if time.time() - os.path.getmtime(CACHE) < CACHE_SECONDS:
            return CACHE
    except OSError:
        pass
    token = os.environ.get("SEARCH_READ_WRITE_TOKEN", "")
    parts = token.split("_")
    if len(parts) < 5 or parts[:3] != ["vercel", "blob", "rw"]:
        raise Unavailable("SEARCH_READ_WRITE_TOKEN is missing or malformed")
    url = f"https://{parts[3].lower()}.private.blob.vercel-storage.com/{PATHNAME}"
    tmp = f"{CACHE}.{os.getpid()}.tmp"
    try:
        req = urllib.request.Request(url, headers={"authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as r, open(tmp, "wb") as f:
            while block := r.read(1 << 20):
                f.write(block)
        os.replace(tmp, CACHE)
    except (OSError, urllib.error.URLError) as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        if os.path.exists(CACHE):  # serve the stale copy rather than nothing
            return CACHE
        raise Unavailable(f"index download failed: {getattr(exc, 'reason', exc)}") from None
    return CACHE


def link(youtube_url: str | None, page: str | None, url: str | None, ts: int) -> str | None:
    """YouTube at the moment when the episode has a video, else a site-relative page, else the publisher's page."""
    video = safe_url(youtube_url)
    if video:
        parts = urlsplit(video)
        query = parts.query + ("&" if parts.query else "") + f"t={ts}s"
        return urlunsplit(parts._replace(query=query))
    return safe_url(page) or safe_url(url)


def safe_url(value: str | None) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) <= 0x20 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if value.startswith("/"):
            return value if not value.startswith("//") and not parts.scheme and not parts.netloc and parts.path.startswith("/") else None
        if parts.scheme != "https" or not parts.netloc or parts.username is not None or parts.password is not None or not parts.hostname:
            return None
    except ValueError:
        return None
    return value


def clock(ts: int) -> str:
    h, m, s = ts // 3600, ts % 3600 // 60, ts % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cap_words(text: str, n: int = MAX_WORDS) -> str:
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    out = " ".join(words[:n])
    return out + "]]" if out.count("[[") > out.count("]]") else out


def search(q: str, db: str) -> list[dict]:
    """The library's transcript query (sigma/library.py search_transcripts) with a [[match]] snippet of 40 words, capped again below."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        def names(ticker):
            row = con.execute("SELECT names FROM tickers WHERE ticker=?", (ticker,)).fetchone()
            return json.loads(row[0]) if row else []

        match = fts_query(q, names)
        if not match:
            return []
        rows = con.execute(
            "SELECT k.episode_id, k.ts, snippet(chunks_fts, 0, '[[', ']]', ' ... ', 40), e.show, e.title, e.published, e.url, e.youtube_url, e.page "
            "FROM chunks_fts JOIN chunks k ON k.id = chunks_fts.rowid JOIN episodes e ON e.episode_id = k.episode_id "
            "WHERE chunks_fts MATCH ? ORDER BY chunks_fts.rank LIMIT ?", (match, CANDIDATES)).fetchall()
    finally:
        con.close()
    out, per = [], {}
    for eid, ts, snip, show, title, date, url, youtube, page in rows:
        if per.get(eid, 0) < PER_EPISODE:
            per[eid] = per.get(eid, 0) + 1
            out.append({"show": show, "title": title, "date": date, "timestamp": int(ts), "time": clock(int(ts)), "snippet": cap_words(snip),
                        "link": link(youtube, page, url, int(ts))})
        if len(out) == MAX_RESULTS:
            break
    return out


def respond(raw_query: str) -> tuple[int, dict, str]:
    """(status, body, cache-control) for the query string of a request."""
    q = " ".join((parse_qs(raw_query).get("q") or [""])[0].split())
    if not q:
        return 400, {"error": "q is empty"}, "no-store"
    if len(q) > MAX_QUERY_CHARS:
        return 400, {"error": f"q is longer than {MAX_QUERY_CHARS} characters"}, "no-store"
    try:
        return 200, {"q": q, "results": search(q, index_path())}, "public, s-maxage=300, stale-while-revalidate=3600"
    except (Unavailable, sqlite3.Error) as exc:
        print(f"[search] unavailable: {exc}", file=sys.stderr)
        return 503, {"error": "search is unavailable"}, "no-store"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body, cache = respond(urlsplit(self.path).query)
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
