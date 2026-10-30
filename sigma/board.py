"""The ticker board: stance labels (stance.py) added up per US-listed ticker, with recent items counting most. The same
sum, with the same weights, runs over the three market targets (MARKET_LINES): Market, Rates, Credit.

    score = sum over items of  stance x KIND_WEIGHT[kind] x quality x 0.5 ** (age_days / HALF_LIFE_DAYS)

over items at most MAX_AGE_DAYS old. Age runs from the item's date (the episode's publish date, the X edition's
date, the X post's date) to the build date. `bull` and `bear` are the positive and negative parts of the same sum kept apart, because
the net hides disagreement; `sources` counts distinct episodes and X accounts behind a ticker. The board is the Sentiment
page, /sentiment/ (site.board_pages).

Standard library only, because the site host builds with nothing else.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import stance, tickers

# Change a number here only.
HALF_LIFE_DAYS = 30                                  # a stance loses half its weight a month, so a quiet week barely moves it
MAX_AGE_DAYS = 90                                    # older items are left out; by then an item weighs 1/8
KIND_WEIGHT = {"deep": 1.0, "social": 1.0, "x": 0.5}  # interviews, YouTube creators' calls, X posts
# How much a mild view (+1/-1) counts against a strong one (+2/-2 counts 2). Strong opinions move the board; mild ones
# barely do, and on X, which is noisy, not at all.
MILD = {"deep": 0.25, "social": 0.25, "x": 0.0}
UNSCORED_QUALITY = 0.6                               # an episode with no score, and every X post; else score / 10
TOP_ITEMS = 5                                        # items listed under a ticker, largest contribution first
# The market lines, in page order: target -> (label, a few words on what it covers). Rates reads up when easing is expected.
MARKET_LINES = {"@MARKET": ("Market", "US stocks"), "@RATES": ("Rates", "Bullish = easing"),
                "@CREDIT": ("Credit", "Spreads, high yield")}

HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")


def contribution(stance_: int, kind: str, quality: float, age_days: int) -> float:
    strength = 2 if abs(stance_) >= 2 else 2 * MILD[kind] * abs(stance_)
    return (1 if stance_ > 0 else -1) * strength * KIND_WEIGHT[kind] * quality * 0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)


def _age(d: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(d)[:10])).days
    except ValueError:
        return None


def collect(published: Path, episodes: dict, us: dict, labels: dict) -> list[dict]:
    """One record per labelled (item, ticker). `episodes` is {episode_id: (kind, score)} for every episode the site
    shows, so a claim from an episode the site does not list is left out. An episode's claims come from the newest dated
    run with labels for it, because a daily and a weekly word the same claim differently; a run published without labels
    never hides older ones; ticker labels and market labels are owned apart, so a run labelled only for the market never
    takes an episode's tickers from the run that has them. The first copy of an item wins."""
    runs = sorted((p for p in Path(published).iterdir() if p.is_dir() and (p / "claims.jsonl").exists()),
                  key=lambda p: p.name if DATED.match(p.name) else "", reverse=True)  # a custom run's free name ranks last
    claims = [(d.name, c, stance.claim_key(c.get("episode_id"), c.get("timestamp"), c.get("text")))
              for d in runs for c in stance.read_jsonl(d / "claims.jsonl")]
    owner: dict = {}
    for run, c, key in claims:
        for lab in labels.get(key, []):
            owner.setdefault((c.get("episode_id"), lab["ticker"] in stance.MARKET), run)
    out, seen, taken = [], set(), set()
    for run, c, key in claims:
        kind_score = episodes.get(c.get("episode_id"))
        if key in labels and kind_score:
            kind, score = kind_score
            for lab in labels[key]:
                is_market = lab["ticker"] in stance.MARKET
                if owner.get((c.get("episode_id"), is_market)) != run or (key, lab["ticker"]) in taken:
                    continue
                taken.add((key, lab["ticker"]))
                out.append({"key": key, "ticker": lab["ticker"], "stance": lab["stance"], "reason": lab["reason"], "kind": kind,
                            "quality": score / 10 if isinstance(score, (int, float)) else UNSCORED_QUALITY,
                            "date": str(c.get("date") or c.get("published") or "")[:10], "sources": [c["episode_id"]],
                            "who": c.get("speaker") or "", "where": c.get("show") or "", "link": c.get("link") or c.get("url") or ""})
    # X: a day whose posts are labelled counts those posts; the edition sentences that sum them up would count them twice.
    # A day with only sentence labels (labelled before posts were) counts its sentences.
    posted = stance.post_rows(published)
    # A post that a thread row lists was labelled alone before its author's self-replies became one item (stance.post_items):
    # the thread's first post carries the one view, so the posts it lists stop counting.
    in_thread = {i for ids in stance.threads_recorded(published).values() for i in ids}
    for day, rows in sorted(posted.items(), reverse=True):
        for r in rows:
            handle, post_id = str(r["handle"]), str(r["id"])
            if post_id in in_thread:
                continue
            if r["key"] in seen or r["key"] not in labels or not HANDLE.fullmatch(handle) or not post_id.isdigit():
                continue
            seen.add(r["key"])
            for lab in labels[r["key"]]:
                out.append({"key": r["key"], "ticker": lab["ticker"], "stance": lab["stance"], "reason": lab["reason"], "kind": "x",
                            "quality": UNSCORED_QUALITY, "date": str(r["date"])[:10], "sources": [handle], "who": "@" + handle,
                            "where": "X", "link": f"https://x.com/{handle}/status/{post_id}"})
    editions = Path(published) / "x" / "editions"
    for f in sorted(editions.glob("*.json"), reverse=True) if editions.is_dir() else []:
        try:
            ed = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if str(ed.get("date") or f.stem) in posted:
            continue
        handle_of = {p.get("id"): p.get("handle") for p in ed.get("posts") or [] if isinstance(p, dict)}
        for it in stance.x_items(ed, us):
            if it["key"] in seen or it["key"] not in labels:
                continue
            seen.add(it["key"])
            posts = [(i, handle_of[i]) for i in it["cites"] if HANDLE.fullmatch(str(handle_of.get(i))) and str(i).isdigit()]
            handles = list(dict.fromkeys(h for _, h in posts))
            link = f"https://x.com/{posts[0][1]}/status/{posts[0][0]}" if posts else ""
            for lab in labels[it["key"]]:
                out.append({"key": it["key"], "ticker": lab["ticker"], "stance": lab["stance"], "reason": lab["reason"], "kind": "x",
                            "quality": UNSCORED_QUALITY, "date": it["date"], "sources": handles,
                            "who": ", ".join("@" + h for h in handles), "where": "X", "link": link})
    return out


def broad_fund_reads(records: list[dict]) -> list[dict]:
    """A stance on a broad index fund (tickers.BROAD_FUNDS) is also a read of the market: one Market record per item,
    from its strongest fund label, unless the item has a Market label of its own, or takes both sides (long IWM, short
    QQQ is a bet between two funds, not on the market). The fund keeps its own ticker row."""
    own = {r["key"] for r in records if r["ticker"] == "@MARKET"}
    funds: dict[str, list[dict]] = {}
    for r in records:
        if r["ticker"] in tickers.BROAD_FUNDS and r["stance"] and r["key"] not in own:
            funds.setdefault(r["key"], []).append(r)
    best = [max(rs, key=lambda r: abs(r["stance"])) for rs in funds.values() if len({r["stance"] > 0 for r in rs}) == 1]
    return [{**r, "ticker": "@MARKET", "reason": f"{r['ticker']}: {r['reason']}"} for r in best]


def score(records: list[dict], today: date, us: dict) -> dict:
    """{"as_of", "rows", "market"}: `rows` has one row per ticker with a stance other than 0 in the window, most bullish
    first; `market` has one row per MARKET_LINES target in page order, with no items when nothing was said."""
    names = {**us, **{t: line[1] for t, line in MARKET_LINES.items()}}
    rows: dict[str, dict] = {}
    for r in records + broad_fund_reads(records):
        age = _age(r["date"], today)
        if age is None or age > MAX_AGE_DAYS or r["ticker"] not in names:
            continue
        row = rows.setdefault(r["ticker"], {"ticker": r["ticker"], "name": names[r["ticker"]], "net": 0.0, "bull": 0.0, "bear": 0.0,
                                            "mentions": 0, "sources": set(), "last": "", "items": []})
        c = contribution(r["stance"], r["kind"], r["quality"], age)
        row["net"] += c
        row["bull"] += max(c, 0)
        row["bear"] += max(-c, 0)
        row["mentions"] += 1
        row["sources"].update(r["sources"])
        row["last"] = max(row["last"], r["date"])
        if c:
            row["items"].append({**{k: r[k] for k in ("who", "where", "date", "stance", "reason", "link", "kind")}, "weight": abs(c)})
    out = []
    for row in rows.values():
        if not row["items"]:
            continue
        row["items"] = sorted(row["items"], key=lambda i: (-i["weight"], i["date"], i["who"]))[:TOP_ITEMS]
        out.append({**row, "sources": len(row["sources"])})
    by = {r["ticker"]: r for r in out}
    market = [{**by[t], "label": line[0]} if t in by else
              {"ticker": t, "label": line[0], "name": line[1], "net": 0.0, "bull": 0.0, "bear": 0.0, "mentions": 0, "sources": 0, "last": "", "items": []}
              for t, line in MARKET_LINES.items()]
    out = sorted((r for r in out if r["ticker"] not in MARKET_LINES), key=lambda r: (-r["net"], -r["bull"], r["ticker"]))
    return {"as_of": today.isoformat(), "rows": out, "market": market}


def pacific_tz():
    """Pacific time, where the issues are dated: the site host's clock is often UTC, a day ahead every evening."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:  # no time zone database on the host: standard time is close enough
        return timezone(timedelta(hours=-8))


def publication_day(value) -> str:
    raw = str(value or "")
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10]
    if len(raw) <= 10:
        return moment.date().isoformat()
    moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(pacific_tz()).date().isoformat()


def pacific_today() -> date:
    return datetime.now(pacific_tz()).date()


def build(published: Path, episodes: dict, today: date | None = None, us: dict | None = None) -> dict:
    us = tickers.load() if us is None else us
    return score(collect(published, episodes, us, stance.labelled(published)), today or pacific_today(), us)
