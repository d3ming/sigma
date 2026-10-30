"""Stance labels: for every (claim, ticker) pair, how bullish or bearish the speaker is on that stock, -2 to +2. A label
may also name a market target (@MARKET, @RATES, @CREDIT): the item's view of US stocks overall, of rates, of credit.

Code does the mechanical parts, a reader agent (prompts/stance.md) does the judgment, as in rank.py:
`stance-prep` writes `stance/in-N.json` batches of items not yet labelled, the reader saves `stance/out-N.json`, and
`stance-merge` checks it and appends the rows to the file the board reads:

    podcast claims   data/published/<run>/stances.jsonl          (items from data/published/<run>/claims.jsonl)
    X posts          data/published/x/stances/<date>.jsonl       (items from the day's scan, <x dir>/scan/<date>/posts.jsonl)

An X post is labelled itself, not through the edition sentence that sums it up, so a post and its sentence never count
twice. Its row also carries what the board shows, because the site host has no scan: the post's `id`, `handle` and `date`,
never its text. The file may still hold sentence rows (`x-...` keys, labelled before posts were); the board reads them
only for a day with no post rows (board.collect).

An item's key is a hash, so a rewritten claim or sentence is a new item: `c-<12 hex>` of episode id, timestamp and text for a
podcast claim; `p-<post id>` for an X post (a thread of the author's own replies is one item, keyed by its first post, and its row
lists the other posts' ids in `thread`); `x-<12 hex>` of date, section, index and text for an edition sentence.

One row per item: {"key", "labels": [{"ticker", "stance", "reason"}], "market": true}. A labelled item keeps its label,
like a score: prep skips every key any file already holds. Only US-listed tickers count (tickers.py). `market` says the
item was read for market targets (a claim whose words read like a market view, every X sentence). An item labelled
before market targets existed has no such flag, so prep offers it again for market labels only and merge appends a
second row with just those; labelled() joins the rows of a key. The board (board.py) turns the labels into scores.

Standard library only at import, because the site host builds with nothing else.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import tickers
from .paths import data_root

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = data_root() / "published"
STANCE_DIR = "stance"
BATCH = 40              # items per reader file
STANCE_RANGE = (-2, 2)
MAX_REASON_WORDS = 15
SECTIONS = ("signals",)
# Reserved target names: "@" is in no ticker, so they never collide with one. A claim or sentence about the market
# itself is labelled with one of them, besides or instead of tickers.
MARKET = {"@MARKET": "US stocks overall", "@RATES": "rates, the Fed, Treasuries, yields", "@CREDIT": "credit spreads, high yield, private credit"}
# Words that make a claim a candidate for a market label even when it names no ticker; the reader decides. Tuned on the
# published claims (2026-10-27): "valuation", "default", "volatility", "multiple" and "debt" matched funding rounds,
# settings and single companies' balance sheets.
MARKET_WORDS = re.compile(r"""\b(?:
    stock\ market|equity\ market|equities|stocks|markets|s&p|nasdaq|dow\ jones|russell\ 2000|wall\ street|index\ funds?|etfs?|
    fed|federal\ reserve|fomc|rate\ (?:cuts?|hikes?|path)|interest\ rates?|rates|yields|yield\ curve|treasur(?:y|ies)|
    inflation|disinflation|recession|soft\ landing|gdp|tariffs?|
    credit|bonds?|spreads|high[-\ ]yield|defaults|deficits?|
    sell-?offs?|rall(?:y|ies)|(?<!error-)corrections?|bubble|crash|risk-(?:on|off)|bull\ market|bear\ market|vix|liquidity
)\b""", re.X | re.I)


class StanceError(ValueError):
    pass


# ---------------------------------------------------------------- items and their keys

def _digest(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def claim_key(episode_id, timestamp, text) -> str:
    return "c-" + _digest(episode_id, timestamp, text)


def x_key(date: str, section: str, index: int, text: str) -> str:
    return "x-" + _digest(date, section, index, text)


def post_key(post_id) -> str:
    return "p-" + str(post_id)


def reads_market(text) -> bool:
    return bool(MARKET_WORDS.search(str(text or "")))


def target(sym, us: dict) -> str:
    """The listed spelling of a US ticker, or a market target (@RATES), or "" when it is neither."""
    s = str(sym or "").strip().upper()
    return s if s in MARKET else tickers.valid(sym, us)


def candidates(symbols, us: dict) -> list[str]:
    """The distinct US-listed tickers among `symbols`, in the listed spelling."""
    out: list[str] = []
    for s in symbols or []:
        if isinstance(s, str) and (v := tickers.valid(s, us)) and v not in out:
            out.append(v)
    return out


def read_jsonl(p: Path) -> list[dict]:
    rows = []
    try:
        for line in p.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


def claim_items(rows: list[dict], us: dict) -> list[dict]:
    """One item per claim that names a US ticker or reads like a market view (claims.jsonl rows). A claim repeated across
    issues is one item."""
    seen, out = set(), []
    for c in rows:
        text, eid = c.get("text"), c.get("episode_id")
        cand = candidates(c.get("tickers"), us)
        if not (text and eid and (cand or reads_market(text))):
            continue
        key = claim_key(eid, c.get("timestamp"), text)
        if key not in seen:
            seen.add(key)
            out.append({"key": key, "kind": "claim", "date": str(c.get("date") or c.get("published") or "")[:10],
                        "show": c.get("show"), "title": c.get("title"), "speaker": c.get("speaker"), "text": text,
                        "candidates": cand, "market": reads_market(text), "episode_id": eid,
                        "timestamp": c.get("timestamp")})
    return out


def x_items(ed: dict, us: dict) -> list[dict]:
    """One item per Signals sentence of an edition. Its candidates are the cashtags of the posts it cites; the
    reader may name other tickers, because the sentence is about whatever it says. The reader sees every sentence whole,
    so every one is read for market targets too."""
    date = str(ed.get("date") or "")
    posts = {p["id"]: p for p in ed.get("posts") or [] if isinstance(p, dict) and p.get("id")}
    out = []
    for section in SECTIONS:
        for i, s in enumerate(ed.get(section) or []):
            if not (isinstance(s, dict) and s.get("text")):
                continue
            cites = [c for c in s.get("cites") or [] if c in posts]
            handles = list(dict.fromkeys(posts[c].get("handle") for c in cites if posts[c].get("handle")))
            out.append({"key": x_key(date, section, i, s["text"]), "kind": "x", "date": date, "section": section,
                        "text": s["text"], "accounts": handles, "cites": cites, "market": True,
                        "candidates": candidates([t for c in cites for t in posts[c].get("cashtags") or []], us)})
    return out


URL = re.compile(r"https?://\S+")
MIN_POST_WORDS = 3   # words of the author's own, besides links, @names and cashtags: fewer is a bare link or a bare repost


def _plain(text) -> str:
    return " ".join(URL.sub(" ", str(text or "")).split())


def _pacific_day(created_at, tz) -> str:
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(tz).date().isoformat()
    except ValueError:
        return str(created_at or "")[:10]


def _thread_roots(posts: list[dict]) -> dict[str, str]:
    """post id -> the id of its thread's first post present in the scan, for posts of one author's own thread. Two posts
    of the same handle are one thread when one replies to the other (`in_reply_to_id`, followed link by link) or when they
    share a `conversation_id`. A thread whose first post is outside the scan starts at its earliest present post."""
    mine = [p for p in posts if p.get("id") and p.get("handle") and not p.get("is_repost")
            and not str(p.get("text") or "").startswith("RT @")
            and not (p.get("in_reply_to_id") and str(p.get("in_reply_to_handle") or "").lower() != str(p["handle"]).lower())]
    by_id = {str(p["id"]): p for p in mine}
    parent: dict[str, str] = {i: i for i in by_id}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    first_of: dict[tuple[str, str], str] = {}
    for i, p in by_id.items():
        up = str(p.get("in_reply_to_id") or "")
        if up in by_id and str(by_id[up]["handle"]).lower() == str(p["handle"]).lower():
            join(i, up)
        if p.get("conversation_id"):
            join(i, first_of.setdefault((str(p["handle"]).lower(), str(p["conversation_id"])), i))
    groups: dict[str, list[str]] = {}
    for i in by_id:
        groups.setdefault(find(i), []).append(i)
    order = lambda i: (str(by_id[i].get("created_at") or ""), len(i), i)
    return {i: min(ids, key=order) for ids in groups.values() for i in ids}


def post_items(posts: list[dict], quoted: dict, us: dict, names: dict | None = None) -> list[dict]:
    """One item per scanned post that names a US ticker or reads like a market view. `names` maps a company name (lower
    case) to its US ticker (entities.py), so "Microsoft" counts without a cashtag. Reposts, replies to other people and
    posts with no words of their own (a bare link, an emoji over a quoted post) are not candidates. An author's replies to
    themselves are one item with the first post of the thread (`_thread_roots`): its key, link and day are the first
    post's, its text is the posts in order, and it is read once, so a thread makes one view and not one per post. The
    reader sees every post whole, with the posts they quote, so every one is read for market targets too. An item's date is
    the first post's day in Pacific time, where Sigma dates everything: an evening post is stamped UTC the next day."""
    from . import board

    tz = board.pacific_tz()
    root_of = _thread_roots(posts)
    threads: dict[str, list[dict]] = {}
    for p in {str(p["id"]): p for p in posts if str(p.get("id")) in root_of}.values():  # a post listed twice counts once
        threads.setdefault(root_of[str(p["id"])], []).append(p)
    out = []
    for root_id, members in threads.items():
        members.sort(key=lambda p: (str(p.get("created_at") or ""), len(str(p["id"])), str(p["id"])))
        root = next(p for p in members if str(p["id"]) == root_id)
        parts = [t for t in (_plain(p.get("text")) for p in members) if t]
        text = "\n\n".join(parts)
        if len(re.findall(r"[^\W\d_]{2,}", re.sub(r"[@$]\w+", " ", text))) < MIN_POST_WORDS:
            continue
        named = [t for name, t in (names or {}).items() if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text, re.I)]
        cand = candidates([*(c for p in members for c in p.get("cashtags") or []), *named], us)
        if not (cand or reads_market(text)):
            continue
        qs = [quoted[q] for q in dict.fromkeys(p.get("quoted_id") for p in members) if q and q in quoted]
        rest = [str(p["id"]) for p in members if str(p["id"]) != root_id]
        out.append({"key": post_key(root["id"]), "kind": "post", "date": _pacific_day(root.get("created_at"), tz), "id": root["id"],
                    "handle": root["handle"], "text": text, "candidates": cand, "market": True, **({"thread": rest} if rest else {}),
                    **({"quoted": "\n".join(f"@{q.get('handle')}: {_plain(q.get('text'))[:600]}" for q in qs)} if qs else {})})
    return out


# ---------------------------------------------------------------- what is labelled

def label_files(published: Path) -> list[Path]:
    """Every stances file, runs by name then X days by date: the order that decides which label wins a duplicate."""
    xd = Path(published) / "x" / "stances"
    return sorted(Path(published).glob("*/stances.jsonl")) + (sorted(xd.glob("*.jsonl")) if xd.is_dir() else [])


def labelled(published: Path) -> dict[str, list[dict]]:
    """key -> labels, from every stances file. The rows of a key are joined (an item read again for market targets has a
    second row); the first label for a (key, ticker) keeps it."""
    out: dict[str, list[dict]] = {}
    for f in label_files(published):
        for r in read_jsonl(f):
            if isinstance(r.get("key"), str) and isinstance(r.get("labels"), list):
                have = out.setdefault(r["key"], [])
                for lab in r["labels"]:
                    if isinstance(lab, dict) and lab.get("ticker") not in {x["ticker"] for x in have}:
                        have.append(lab)
    return out


def market_read(published: Path) -> set[str]:
    """Keys whose item a reader has been given for market targets."""
    return {r["key"] for f in label_files(published) for r in read_jsonl(f)
            if isinstance(r.get("key"), str) and r.get("market") is True}


def post_rows(published: Path) -> dict[str, list[dict]]:
    """X day -> the rows of that day's stances file that label a post (they carry its id, handle and date). A day with no
    such row is one labelled through edition sentences, if at all."""
    xd = Path(published) / "x" / "stances"
    out: dict[str, list[dict]] = {}
    for f in sorted(xd.glob("*.jsonl")) if xd.is_dir() else []:
        rows = [r for r in read_jsonl(f) if str(r.get("key", "")).startswith("p-") and r.get("id") and r.get("handle") and r.get("date")]
        if rows:
            out[f.stem] = rows
    return out


def threads_recorded(published: Path) -> dict[str, set[str]]:
    """root post key -> ids of the thread's other posts, from the `thread` field of any X post row. Those posts are part
    of the root's one view: the board skips their own rows (board.collect)."""
    out: dict[str, set[str]] = {}
    for rows in post_rows(published).values():
        for r in rows:
            if isinstance(r.get("thread"), list):
                out.setdefault(r["key"], set()).update(str(i) for i in r["thread"])
    return out


def thread_notes(items: list[dict], known: dict, recorded: dict[str, set[str]], fresh: set[str]) -> list[dict]:
    """Rows that supersede posts labelled one by one before threads were one item: for a thread whose root is labelled (not
    in `fresh`, which carry their own `thread`) and whose other posts have labels or are not yet on the root's row, a row
    with no labels but the thread's ids. The root keeps its label and the posts' rows are left as they are (a label is made
    once); the board stops counting them."""
    return [{"key": it["key"], "labels": [], "id": it["id"], "handle": it["handle"], "date": it["date"], "thread": it["thread"]}
            for it in items if it.get("thread") and it["key"] in known and it["key"] not in fresh
            and any(post_key(i) in known for i in it["thread"]) and not set(it["thread"]) <= recorded.get(it["key"], set())]


def pending(items: list[dict], done: dict, read: set[str]) -> list[dict]:
    """What a reader is still owed: items nothing has labelled, and labelled items that read like a market view and were
    never read for one (`market_only`: market labels only, the ticker labels stay)."""
    out = []
    for it in items:
        if it["key"] not in done:
            out.append(it)
        elif it["market"] and it["key"] not in read:
            out.append({**it, "market_only": True, "candidates": []})
    return out


# ---------------------------------------------------------------- prep

def _target(run: str | None, x: str | None, published: Path) -> tuple[Path, Path, list[dict], str]:
    """(batch folder, stances file, items, label) for a run folder or an X date."""
    us = tickers.load()
    if not us:
        raise StanceError(f"{tickers.FILE} is missing or empty: run sigma tickers-refresh")
    if x:
        from . import entities, xdaily

        sd = xdaily.scan_dir(x)
        if not (sd / "posts.jsonl").exists():
            raise StanceError(f"no scan {sd}/posts.jsonl: the scanner has not delivered {x}")
        ent = entities.load()
        # a name that reads as a market word ("Nasdaq", the index, for NDAQ) is not evidence of the company
        names = {str(n).lower(): c["ticker"] for c in ent.companies.values() if c.get("ticker")
                 for n in [c.get("name"), *(c.get("aliases") or [])] if n and len(str(n)) >= 4 and not reads_market(n)}
        items = post_items(xdaily.read_jsonl(sd / "posts.jsonl"), {q["id"]: q for q in xdaily.read_jsonl(sd / "quoted.jsonl")}, us, names)
        return xdaily.day_dir(x) / STANCE_DIR, Path(published) / "x" / "stances" / f"{x}.jsonl", items, f"X {x}"
    if not run:
        raise StanceError("give a run folder (runs/<name>) or --x DATE")
    run_dir = Path(run)
    claims = Path(published) / run_dir.name / "claims.jsonl"
    if not claims.exists():
        raise StanceError(f"no {claims}: publish the run first (sigma report / sigma publish)")
    return run_dir / STANCE_DIR, Path(published) / run_dir.name / "stances.jsonl", claim_items(read_jsonl(claims), us), run_dir.name


def prep(run: str | None, x: str | None = None, published: Path = PUBLISHED, batch: int = BATCH) -> dict:
    """Write in-N.json for the items nothing has labelled yet and the labelled ones still owed a market read. Refuses
    while an out-N.json waits to be merged, because new batches are numbered from 1 again."""
    folder, _, items, label = _target(run, x, published)
    if waiting := sorted(folder.glob("out-*.json")):
        raise StanceError(f"{len(waiting)} reader output(s) in {folder} are not merged: run sigma stance-merge first")
    todo = pending(items, labelled(published), market_read(published))
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("in-*.json"):
        old.unlink()
    groups = math.ceil(len(todo) / batch)
    size = math.ceil(len(todo) / groups) if groups else 0
    for k in range(groups):
        (folder / f"in-{k + 1}.json").write_text(json.dumps(todo[k * size:(k + 1) * size], indent=1, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    market_only = sum(1 for it in todo if it.get("market_only"))
    return {"label": label, "folder": folder, "items": len(items), "labelled": len(items) - len(todo) + market_only,
            "to_label": len(todo) - market_only, "market_only": market_only, "batches": groups}


# ---------------------------------------------------------------- merge

def check_output(data, batch_items: dict, us: dict) -> tuple[list[dict], list[str]]:
    """(rows, problems) for one reader output against the items it was given."""
    import jsonschema

    from . import xdaily

    schema = json.loads((ROOT / "schema" / "stance.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        return [], [f"schema: {exc.message} at {'/'.join(map(str, exc.path))}"]
    rows, problems, seen = [], [], set()
    for r in data:
        key, item = r["key"], batch_items.get(r["key"])
        if item is None:
            problems.append(f"{key}: not an item of this batch")
            continue
        if key in seen:
            problems.append(f"{key}: labelled twice")
            continue
        seen.add(key)
        labels, got = [], set()
        for lab in r["labels"]:
            sym = target(lab["ticker"], us)
            if not sym:
                problems.append(f"{key}: {lab['ticker']} is not a US-listed ticker or a market target")
            elif item.get("market_only") and sym not in MARKET:
                problems.append(f"{key}: {sym}: this item is read for market targets only, its ticker labels are kept")
            elif sym in got:
                problems.append(f"{key}: {sym} labelled twice")
            else:
                got.add(sym)
                labels.append({"ticker": sym, "stance": lab["stance"], "reason": " ".join(lab["reason"].split()),
                               **{f: lab[f] for f in ("origin", "horizon_days", "target") if lab.get(f) and lab["stance"]}})
            if len(lab["reason"].split()) > MAX_REASON_WORDS:
                problems.append(f"{key}: the reason for {lab['ticker']} is over {MAX_REASON_WORDS} words")
            if item["kind"] == "post" and xdaily.copied_run(lab["reason"], item["text"] + " " + item.get("quoted", "")):
                problems.append(f"{key}: the reason for {lab['ticker']} copies the post; put it in your own words")
        if missing := [t for t in item["candidates"] if t not in got] if item["kind"] == "claim" else []:
            problems.append(f"{key}: no label for {', '.join(missing)} (label every candidate; 0 for a mention)")
        rows.append({"key": key, "labels": labels, **({"market": True} if item.get("market") else {}),
                     **({"id": item["id"], "handle": item["handle"], "date": item["date"],
                         **({"thread": item["thread"]} if item.get("thread") else {})} if item["kind"] == "post" else {})})
    return rows, problems


def merge(run: str | None, x: str | None = None, published: Path = PUBLISHED) -> dict:
    """Check every out-N.json against its in-N.json and append the new rows to the stances file. A key some file already
    holds keeps its label, except that an item offered for market labels only (`market_only`) gets a second row with
    them. On any problem nothing is written. Merged batches move to stance/merged/."""
    from .ranked import private_hits

    folder, dest, items, label = _target(run, x, published)
    outs = sorted(folder.glob("out-*.json"))
    us = tickers.load()
    known, read = labelled(published), market_read(published)
    new, problems, only = [], [], set()
    for f in outs:
        n = f.name[len("out-"):-len(".json")]
        try:
            src = json.loads((folder / f"in-{n}.json").read_text(encoding="utf-8"))
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{f.name}: {exc}")
            continue
        only |= {it["key"] for it in src if it.get("market_only")}
        rows, probs = check_output(data, {it["key"]: it for it in src}, us)
        problems += [f"{f.name}: {p}" for p in probs]
        new += rows
    if hits := private_hits(new):
        problems.append(f"the reasons look private: {hits}")
    if problems:
        raise StanceError("\n".join(problems[:40]))
    fresh = [r for r in new if r["key"] not in known or (r["key"] in only and r["key"] not in read)]
    notes = thread_notes(items, known, threads_recorded(published), {r["key"] for r in fresh}) if x else []
    if not outs and not notes:
        if pending(items, known, read):
            raise StanceError(f"no out-N.json in {folder}: give each in-N.json to a reader (prompts/stance.md)")
        return {"label": label, "dest": dest, "added": 0, "kept": 0, "labels": 0, "left": 0, "threads": 0}  # already merged
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        for r in [*fresh, *notes]:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    done_dir = folder / "merged"
    done_dir.mkdir(exist_ok=True)
    for f in [*outs, *folder.glob("in-*.json")]:
        shutil.move(str(f), done_dir / f.name)
    left = len(pending(items, labelled(published), market_read(published)))
    return {"label": label, "dest": dest, "added": len(fresh), "kept": len(new) - len(fresh),
            "labels": sum(len(r["labels"]) for r in fresh), "left": left, "threads": len(notes)}
