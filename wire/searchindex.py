"""Transcript search: export a copy of the library's transcript index, and put it in the private Blob store `wire-search`.

`wire library ingest` already cuts every transcript into ~60 s windows and indexes them (chunks + chunks_fts in
data/library.sqlite). This command copies the episodes that have a transcript, and those windows, into a small file
without claims, scores or run bookkeeping. It leaves out every show with `no_search: true` in sources.yaml, keeps one copy
of an episode that the library holds under two feeds, and adds what the site's /api/search function (api/search.py) needs
to answer: each episode's Wire page and a table that turns a ticker into the company's names (from entities.json). The copy is
never public: the store is private and only the function holds its token. Full transcripts stay off the site.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import library, published
from .config import load_sources
from .site import episode_path
from .sources import norm

PATHNAME = "wire-search/index.sqlite"  # the Blob pathname; api/search.py reads the same one
TOKEN_ENV = "SEARCH_READ_WRITE_TOKEN"  # the wire-search store's read-write token: Vercel (production, preview, development) and .env.local on the Mac
ENV_FILE = published.CONFIG / ".env.local"  # git-ignored
API = "https://vercel.com/api/blob/"
API_VERSION = "13"  # the version @vercel/blob 2.x sends
SCHEMA = """
CREATE TABLE episodes (episode_id TEXT PRIMARY KEY, title TEXT, show TEXT, published TEXT, url TEXT, youtube_url TEXT, page TEXT);
CREATE TABLE chunks (id INTEGER PRIMARY KEY, episode_id TEXT NOT NULL, ts INTEGER);
CREATE INDEX chunks_episode ON chunks(episode_id);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, tokenize='porter unicode61');
CREATE TABLE tickers (ticker TEXT PRIMARY KEY, names TEXT NOT NULL);
"""  # the library's own table names and tokenizer, so the library's query runs unchanged


class SearchIndexError(RuntimeError):
    pass


def no_search_names(sources_path: Path) -> set[str]:
    """Ids, names and aliases (normalised) of the shows with `no_search: true`."""
    sources, _ = load_sources(sources_path)
    return {n for s in sources if s.no_search for n in (norm(s.id), norm(s.name), *map(norm, s.aliases))}


def published_rows(published_root: Path) -> tuple[dict[str, str], set[str]]:
    """({episode_id: youtube_url}, ids of the episodes that have claims). The first come from published/*/episodes.json, the newest
    run's link winning; the second are the episodes the site gives a page of their own."""
    found: dict[str, str] = {}
    with_page: set[str] = set()
    for d in sorted(Path(published_root).glob("*/"), reverse=True):
        try:
            rows = json.loads((d / "episodes.json").read_text())
        except (OSError, ValueError):
            rows = []
        for e in rows if isinstance(rows, list) else []:
            if e.get("episode_id") and e.get("youtube_url"):
                found.setdefault(e["episode_id"], e["youtube_url"])
        try:
            for line in (d / "claims.jsonl").read_text().split("\n"):
                if line.strip():
                    with_page.add(json.loads(line)["episode_id"])
        except (OSError, ValueError, KeyError):
            continue
    return found, with_page


def ticker_names(entities_path: Path) -> dict[str, list[str]]:
    """{TICKER: [company name, aliases...]} from entities.json, for a search that types a ticker."""
    try:
        companies = json.loads(Path(entities_path).read_text()).get("companies") or {}
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for c in companies.values():
        if c.get("ticker"):
            out[c["ticker"].upper()] = list(dict.fromkeys(n for n in [c.get("name"), *(c.get("aliases") or [])] if n and len(n) >= 3))
    return out


def build(library_db: Path, out: Path, published_root: Path = published.ROOT, sources_path: Path = published.CONFIG / "sources.yaml",
          entities_path: Path = published.CONFIG / "entities.json") -> dict:
    """Write the export to `out` (replaced atomically) and return the counts. Reads the library read-only."""
    hidden = no_search_names(sources_path)
    yt, with_page = published_rows(published_root)
    counts = {"episodes": 0, "chunks": 0, "no_search": 0, "duplicates": 0}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=out.name + ".", suffix=".tmp")
    os.close(fd)
    src = library.connect(library_db)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA)
        eps = [dict(r) | {"youtube_url": r["youtube_url"] or yt.get(r["episode_id"])} for r in src.execute(
            "SELECT episode_id, title, show, published, url, youtube_url, run_date FROM episodes WHERE has_transcript=1 "
            "AND EXISTS (SELECT 1 FROM chunks k WHERE k.episode_id=episodes.episode_id)")]
        eps.sort(key=lambda e: (e["run_date"] or "", e["episode_id"]), reverse=True)  # the newest run's copy first ...
        eps.sort(key=lambda e: not e["youtube_url"])  # ... and a copy with a video before one without
        seen: set = set()
        for e in eps:
            if norm(e["show"] or "") in hidden:
                counts["no_search"] += 1
                continue
            passages = src.execute("SELECT k.id, k.ts, f.text FROM chunks k JOIN chunks_fts f ON f.rowid=k.id WHERE k.episode_id=? ORDER BY k.ts, k.id",
                                   (e["episode_id"],)).fetchall()
            # the same episode under two feeds: the same transcript, or the same title on the same day
            keys = {("text", hashlib.sha256(" ".join(p["text"] for p in passages).encode()).hexdigest()),
                    ("title", norm(e["title"] or ""), e["published"])}
            if seen & keys:
                counts["duplicates"] += 1
                continue
            seen |= keys
            con.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?)",
                        (e["episode_id"], e["title"], e["show"], e["published"], e["url"], e["youtube_url"],
                         episode_path(e["episode_id"]) if e["episode_id"] in with_page else None))
            counts["episodes"] += 1
            for k in passages:
                con.execute("INSERT INTO chunks (id, episode_id, ts) VALUES (?,?,?)", (k["id"], e["episode_id"], k["ts"]))
                # the function marks matches with [[ ]], so the text must not carry them
                con.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?,?)", (k["id"], k["text"].replace("[[", "").replace("]]", "")))
                counts["chunks"] += 1
        con.executemany("INSERT INTO tickers VALUES (?,?)", [(t, json.dumps(n)) for t, n in ticker_names(entities_path).items()])
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('optimize')")
        con.commit()
        con.execute("VACUUM")
    except BaseException:
        con.close()
        os.unlink(tmp)
        raise
    finally:
        src.close()
    con.close()
    os.replace(tmp, out)
    return counts | {"bytes": out.stat().st_size}


def env_local(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=value lines of a .env.local (an `export ` prefix and quotes allowed); {} if there is none."""
    out = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip().removeprefix("export ")
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip("'\"")
    return out


def token() -> str:
    """The store's token: the environment first, else .env.local. Never printed."""
    return os.environ.get(TOKEN_ENV) or env_local().get(TOKEN_ENV, "")


def upload(path: Path, tok: str, tries: int = 5) -> None:
    """PUT the file to the private Blob store at PATHNAME, overwriting the last one. Standard library only."""
    body = Path(path).read_bytes()
    headers = {"authorization": f"Bearer {tok}", "x-api-version": API_VERSION, "x-vercel-blob-access": "private",
               "x-add-random-suffix": "0", "x-allow-overwrite": "1", "x-content-type": "application/vnd.sqlite3",
               "content-type": "application/octet-stream"}
    for i in range(tries):
        req = urllib.request.Request(f"{API}?pathname={PATHNAME}", data=body, headers=headers, method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=300):
                return
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(min(float(exc.headers.get("retry-after") or 2 ** i), 30))
                continue
            raise SearchIndexError(f"upload failed: HTTP {exc.code} {exc.read()[:200].decode(errors='replace')}") from None
        except urllib.error.URLError as exc:
            if i == tries - 1:
                raise SearchIndexError(f"upload failed: {exc.reason}") from None
            time.sleep(2 ** i)


def search_index_cmd(args) -> None:
    started = time.monotonic()
    try:
        library.connect(args.library).close()
    except library.LibraryMissing as exc:
        raise SystemExit(f"[search-index] {exc}")
    tok = token() if args.upload else ""
    if args.upload and not tok:
        raise SystemExit(f"[search-index] --upload needs {TOKEN_ENV} in the environment or in .env.local")
    r = build(Path(args.library), Path(args.out))
    print(f"[search-index] {r['episodes']} episodes, {r['chunks']:,} passages; left out {r['no_search']} no_search and {r['duplicates']} duplicate "
          f"copies; {r['bytes'] / 1e6:.1f} MB in {time.monotonic() - started:.1f}s -> {args.out}")
    if args.upload:
        try:
            upload(Path(args.out), tok)
        except SearchIndexError as exc:
            raise SystemExit(f"[search-index] {exc}")
        print(f"[search-index] uploaded to private Blob {PATHNAME}")
