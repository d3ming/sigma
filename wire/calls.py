"""The call ledger: every stock call a creator made, and how the stock did afterwards. Private.

A call is a stance label (stance.py) of +-1 or +-2 on a US ticker, from an item of one of the creator's outlets: a claim
from an episode of one of its `sources`, or an X post by one of its `x` handles (creators.json). The items and their dates
are the board's (board.collect), so the ledger and the Sentiment page agree on what was said. Market targets (@MARKET...)
and broad index funds are not calls on a stock and are left out. A claim counts toward the creator only when its speaker is the
creator or a host of the show (is_host); a named guest's call goes to the show's own guest bucket, so it never moves the
creator's hit rate. Several calls on the same ticker, day and side count once,
at the strongest label.

Each call is followed from the close on its date (the last close on or before it) to the close 5, 21 and 63 trading days
later, where that many have passed: return, return of SPY over the same days, and the excess, signed by the call's side (a
bearish call that falls more than SPY is a hit). Closes are daily adjusted closes from Yahoo's chart endpoint, which needs
no key, cached under data/prices/. Yahoo is unofficial; Stooq, the first choice, now makes a browser prove itself first.

Track records are private: the owner decided they never reach the site or published/. Everything this module writes is
under data/, and nothing on the site path may import it (tests/test_calls.py checks). `summary` is the seam for a later
decision to show a creator's record.

A creator's private outlets (a Substack, a paid site) join the same record without leaving data/: data/creators-private.json
lists a creator's `outlets` (ids), and data/private-calls/<outlet>.jsonl holds the outlet's labelled items as rows
{"date": "YYYY-MM-DD", "link": "", "labels": [{"ticker", "stance", "reason"}]}, which a private ingest writes.

Standard library only.
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_right
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from . import board, creators, stance, tickers

ROOT = Path(__file__).resolve().parent.parent
HORIZONS = (5, 21, 63)   # trading days after the call date's close
STRONG = 2               # |stance| of a strong call; a mild one is 1
PRICE_MAX_AGE = 12 * 3600  # seconds a cached price file is reused
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1d&events=div%2Csplit"


def data_dir() -> Path:
    return ROOT / "data"


# ---------------------------------------------------------------- the calls

def private_outlets(path: Path | None = None) -> dict[str, str]:
    """{outlet id: creator id} from data/creators-private.json."""
    try:
        d = json.loads((path or data_dir() / "creators-private.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {o: cid for cid, c in (d.get("creators") or {}).items() if isinstance(c, dict) for o in c.get("outlets") or []}


def private_records(directory: Path, outlets: dict[str, str]) -> list[dict]:
    """Board-shaped records for the private outlets that some creator lists."""
    out = []
    for f in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        if f.stem not in outlets:
            continue
        for r in stance.read_jsonl(f):
            for lab in r.get("labels") or []:
                out.append({"key": f"{f.stem}:{r.get('key') or ''}", "ticker": lab.get("ticker"), "stance": lab.get("stance"), "kind": "private",
                            "date": str(r.get("date") or "")[:10], "sources": [f.stem], "where": f.stem, "link": r.get("link") or ""})
    return out


def records(published: Path) -> list[dict]:
    """board.collect over every episode that has claims: one record per labelled (item, ticker), X posts included."""
    episodes: dict = {}
    for f in Path(published).glob("*/claims.jsonl"):
        for c in stance.read_jsonl(f):
            if c.get("episode_id"):
                episodes[c["episode_id"]] = ("social", None)
    return board.collect(Path(published), episodes, tickers.load(), stance.labelled(Path(published)))


ROLE_WORDS = {"host", "hosts", "cohost", "co", "presenter", "anchor", "interviewer"}  # "co-host" normalizes to "co host"


def is_host(speaker, names: set[str]) -> bool:
    """Whether a claim's `speaker` is the creator or one of the show's hosts. `names` are the normalized (creators.norm_show)
    names the creator and its listed `hosts` go by. True for such a name, for a role alone ("host", "co-host"), and for a name
    with a role ("Paul (host)"); a guest, a role of a guest ("guest host", "CEO"), a name nobody listed and a blank speaker are not."""
    toks = creators.norm_show(speaker).split()
    if not toks or "guest" in toks:
        return False
    rest = [t for t in toks if t not in ROLE_WORDS]
    role = len(rest) < len(toks)
    return " ".join(toks) in names or (role and (not rest or " ".join(rest) in names))


def guest_key(creator_id: str, source_id: str) -> str:
    """The ledger key of the guests on one of a creator's shows, kept apart from the creator's own record."""
    return f"{creator_id}/guest/{source_id}"


def owner_of(creator_list: list[creators.Creator], names: dict, outlets: dict[str, str]):
    """A function: record -> (creator id, key of the record it counts toward) or None. A claim belongs to the creator whose
    source has its show's name or an alias, and counts toward the creator when the speaker is the creator or a host of that
    show (is_host), else toward that show's guest bucket (guest_key); an X record to the creator who lists its handle (a sentence
    that sums up several accounts belongs to none); a private outlet's item to its creator."""
    shows = {creators.norm_show(n): (c, s) for c in creator_list for s in c.sources for n in names.get(s, [])}
    handles = {h.lower(): c.id for c in creator_list for h in c.x}
    hosts = {c.id: {creators.norm_show(n) for n in (c.name, *c.hosts)} for c in creator_list}

    def owner(r: dict):
        if r["kind"] == "private":
            cid = outlets.get(r["where"])
            return (cid, cid) if cid else None
        if r["kind"] == "x":
            cid = handles.get(str(r["sources"][0]).lower()) if len(r["sources"]) == 1 else None
            return (cid, cid) if cid else None
        hit = shows.get(creators.norm_show(r["where"]))
        if not hit:
            return None
        c, source = hit
        return (c.id, c.id if is_host(r.get("who"), hosts[c.id]) else guest_key(c.id, source))

    return owner


def calls(recs: list[dict], owner, us: dict, only: str | None = None) -> list[dict]:
    """The calls among `recs`: stance of +-1 or more on a US ticker that is not a broad fund, with a valid date, deduplicated
    per (credited record, ticker, date, side) at the strongest label. `creator` is the creator whose outlet carried the call;
    `credit` is the record it counts toward (the creator's id, or a guest bucket's key); `only` is a creator id."""
    best: dict[tuple, dict] = {}
    for r in recs:
        got = owner(r)
        sym = r["ticker"]
        if not got or (only and got[0] != only) or sym not in us or sym in tickers.BROAD_FUNDS or not isinstance(r["stance"], int) or abs(r["stance"]) < 1:
            continue
        try:
            date.fromisoformat(r["date"])
        except ValueError:
            continue
        cid, credit = got
        k = (credit, sym, r["date"], r["stance"] > 0)
        if k not in best or abs(r["stance"]) > abs(best[k]["stance"]):
            best[k] = {"creator": cid, "credit": credit, "ticker": sym, "stance": r["stance"], "date": r["date"],
                       "outlet": r["where"] if r["kind"] != "x" else "X " + str(r["sources"][0]), "speaker": r.get("who") or "",
                       "link": r.get("link") or ""}
    return sorted(best.values(), key=lambda c: (c["credit"], c["date"], c["ticker"]))


# ---------------------------------------------------------------- prices

def parse_chart(raw: dict, now: datetime | None = None) -> list[list]:
    """[[date, adjusted close], ...] from Yahoo's chart JSON, oldest first. A day still trading (a bar dated today before 17:00
    New York time) is left out: its close is not one yet."""
    res = raw["chart"]["result"][0]
    off = res["meta"].get("gmtoffset") or 0
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or res["indicators"]["quote"][0]["close"]
    now = now or datetime.now(_new_york())
    out = []
    for ts, px in zip(res.get("timestamp") or [], adj):
        d = datetime.fromtimestamp(ts + off, timezone.utc).date()
        if px is not None and not (d >= now.date() and now.hour < 17):
            out.append([d.isoformat(), float(px)])
    return out


def _new_york():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


def fetch_bars(sym: str) -> list[list]:
    req = Request(YAHOO.format(sym=sym), headers={"User-Agent": "Mozilla/5.0 (Macintosh) wire-calls"})
    with urlopen(req, timeout=30) as r:
        return parse_chart(json.loads(r.read()))


def load_prices(symbols, directory: Path, fetch=fetch_bars, refresh: bool = False, now: float | None = None) -> dict[str, dict[str, float]]:
    """{symbol: {date: close}}. A cached file younger than PRICE_MAX_AGE is reused; a symbol that cannot be fetched is
    reported and left out (its calls get no returns)."""
    import time

    now = time.time() if now is None else now
    out = {}
    for sym in sorted(set(symbols)):
        f = directory / f"{sym}.json"
        try:
            cached = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
        if cached and not refresh and now - cached.get("fetched", 0) < PRICE_MAX_AGE:
            bars = cached["bars"]
        else:
            try:
                bars = fetch(sym)
            except Exception as exc:  # network, a delisted symbol, a changed reply: say it and go on
                print(f"[calls] no prices for {sym}: {type(exc).__name__}: {exc}", file=sys.stderr)
                bars = cached["bars"] if cached else []
            else:
                directory.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps({"fetched": now, "bars": bars}) + "\n", encoding="utf-8")
        if bars:
            out[sym] = {d: p for d, p in bars}
    return out


# ---------------------------------------------------------------- returns

def follow(call: dict, px: dict[str, float], spy: dict[str, float]) -> dict:
    """{horizon: {"ret", "spy", "excess", "signed"}} for the horizons that have elapsed. Trading days are SPY's; the call
    starts at the last close on or before its date, and a horizon needs the stock's close on both days."""
    days = sorted(spy)
    i = bisect_right(days, call["date"]) - 1
    out = {}
    if i < 0 or days[i] not in px:
        return out
    p0, s0, side = px[days[i]], spy[days[i]], 1 if call["stance"] > 0 else -1
    for h in HORIZONS:
        if i + h < len(days) and days[i + h] in px:
            r, s = px[days[i + h]] / p0 - 1, spy[days[i + h]] / s0 - 1
            out[h] = {"ret": r, "spy": s, "excess": r - s, "signed": side * (r - s)}
    return out


def ledger(recs: list[dict], owner, us: dict, prices: dict, only: str | None = None) -> list[dict]:
    """The calls with the returns that prices allow."""
    spy = prices.get("SPY") or {}
    out = []
    for c in calls(recs, owner, us, only):
        out.append({**c, "h": follow(c, prices.get(c["ticker"]) or {}, spy)})
    return out


def _stats(rows: list[float]) -> dict:
    n = len(rows)
    hits = sum(1 for x in rows if x > 0)
    return {"n": n, "hits": hits, "hit_rate": hits / n if n else None, "mean_signed_excess": sum(rows) / n if n else None}


def summary(led: list[dict]) -> dict[str, dict]:
    """{credit key (a creator id, or a guest bucket's): {"calls", "strong", "mild", "horizons": {h: {"strong": stats, "mild": stats}}}}, stats being n, hits,
    hit_rate and mean_signed_excess over the calls whose horizon has elapsed (None when there are none). The seam a later
    decision to publish a creator's record would use; today only `wire calls` reads it."""
    out: dict[str, dict] = {}
    for c in led:
        s = out.setdefault(c["credit"], {"calls": 0, "strong": 0, "mild": 0, "rows": {h: {"strong": [], "mild": []} for h in HORIZONS}})
        kind = "strong" if abs(c["stance"]) >= STRONG else "mild"
        s["calls"] += 1
        s[kind] += 1
        for h, v in c["h"].items():
            s["rows"][h][kind].append(v["signed"])
    return {cid: {"calls": s["calls"], "strong": s["strong"], "mild": s["mild"],
                  "horizons": {h: {k: _stats(v) for k, v in by.items()} for h, by in s["rows"].items()}} for cid, s in out.items()}


# ---------------------------------------------------------------- command

def _cell(s: dict) -> str:
    return f"{s['n']:>3} {s['hit_rate']:>4.0%} {s['mean_signed_excess']:>+7.1%}" if s["n"] else "  -      -       -"


def credit_names(crs: list[creators.Creator], source_names: dict) -> dict[str, str]:
    """{credit key: label}: a creator's name, and "<show> guests" for each guest bucket."""
    out = {c.id: c.name for c in crs}
    out.update({guest_key(c.id, s): f"{(source_names.get(s) or [s])[0]} guests" for c in crs for s in c.sources})
    return out


def table(summ: dict, names: dict[str, str]) -> str:
    """One row per creator (or guest bucket) and horizon that has any elapsed call: strong then mild as n, hit rate, mean signed excess over SPY."""
    lines = [f"{'creator':<24} {'calls':>5} {'S/M':>6}  {'days':>4}  {'strong n  hit   mean':<22}{'mild n  hit   mean'}"]
    for cid, s in sorted(summ.items(), key=lambda kv: (-kv[1]["calls"], kv[0])):
        shown = False
        for h in HORIZONS:
            st, ml = s["horizons"][h]["strong"], s["horizons"][h]["mild"]
            if st["n"] or ml["n"]:
                lead = f"{names.get(cid, cid)[:24]:<24} {s['calls']:>5} {str(s['strong']) + '/' + str(s['mild']):>6}" if not shown else " " * 37
                lines.append(f"{lead}  {h:>4}  {_cell(st):<22}{_cell(ml)}")
                shown = True
        if not shown:
            lines.append(f"{names.get(cid, cid)[:24]:<24} {s['calls']:>5} {str(s['strong']) + '/' + str(s['mild']):>6}  no horizon has elapsed yet")
    return "\n".join(lines)


def calls_cmd(args) -> None:
    pub = Path(args.published)
    us = tickers.load()
    crs = creators.load()
    if args.creator and args.creator not in {c.id for c in crs}:
        raise SystemExit(f"[calls] no creator {args.creator!r} in creators.json: " + ", ".join(c.id for c in crs))
    outlets = private_outlets()
    owner = owner_of(crs, creators.source_names(), outlets)
    recs = records(pub) + private_records(data_dir() / "private-calls", outlets)
    symbols = {c["ticker"] for c in calls(recs, owner, us, args.creator)} | {"SPY"}
    prices = load_prices(symbols, data_dir() / "prices", refresh=args.refresh)
    led = ledger(recs, owner, us, prices, args.creator)
    summ = summary(led)
    out = data_dir() / "calls" / (f"ledger-{args.creator}.json" if args.creator else "ledger.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    last = max(prices.get("SPY") or {"": ""})
    out.write_text(json.dumps({"as_of_close": last, "horizons": list(HORIZONS), "calls": led, "summary": summ}, indent=1) + "\n", encoding="utf-8")
    print(table(summ, credit_names(crs, creators.source_names())) if summ else "[calls] no labelled calls from any creator's outlets")
    print(f"[calls] {len(led)} calls from {len({c['creator'] for c in led})} creators, prices to {last}; wrote {out} (private: never published, never on the site)")
