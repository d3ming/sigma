"""Collect source-backed stance records and summarize each speaker once per ticker."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import creators, signals_sentiment, stance, tickers

MAX_AGE_DAYS = 30
UNSCORED_QUALITY = 0.6                               # an episode with no score, and every X post; else score / 10
# The market lines, in page order: target -> (label, a few words on what it covers). Rates reads up when easing is expected.
MARKET_LINES = {"@MARKET": ("Market", "US stocks"), "@RATES": ("Rates", "Bullish = easing"),
                "@CREDIT": ("Credit", "Spreads, high yield")}

HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")




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
                            "who": c.get("speaker") or "", "where": c.get("show") or "", "link": c.get("link") or c.get("url") or "", "origin": lab.get("origin", "recap")})
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
                            "where": "X", "link": f"https://x.com/{handle}/status/{post_id}", "origin": lab.get("origin", "recap")})
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
                            "who": ", ".join("@" + h for h in handles), "where": "X", "link": link, "origin": lab.get("origin", "recap")})
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
    names = {**us, **{t: line[1] for t, line in MARKET_LINES.items()}}
    identity = {name.casefold(): creator.name for creator in creators.load()
                for name in (creator.name, *("@" + handle for handle in creator.x))}
    groups = {}
    for index, record in enumerate(records + broad_fund_reads(records)):
        age = _age(record["date"], today)
        if age is None or not 0 <= age < MAX_AGE_DAYS or record["ticker"] not in names:
            continue
        who = record["who"].strip()
        if not who or who.lower() in {"host", "guest", "unknown"}:
            who = str(record["sources"][0])
        who = identity.get(who.casefold(), who)
        groups.setdefault(record["ticker"], []).append({**record, "speaker": who, "id": record.get("key") or str(index),
                                                     "target": names[record["ticker"]], "origin": record.get("origin", "recap")})
    out = []
    for ticker, rows in groups.items():
        if not any(row["stance"] for row in rows):
            continue
        by_speaker = {}
        for row in rows:
            by_speaker.setdefault(row["speaker"], []).append(row)
        directional = [row for row in rows if row["stance"]]
        neutral = len(set(by_speaker) - {row["speaker"] for row in directional})
        aggregate = signals_sentiment.row(ticker, names[ticker], directional, neutral)
        evidence = []
        for speaker, items in by_speaker.items():
            supporting = sorted(items, key=lambda item: (item["date"], abs(item["stance"]), item["id"]), reverse=True)
            vote = signals_sentiment.row(ticker, names[ticker], [item for item in items if item["stance"]] or items)["net"]
            evidence.append({**supporting[0], "speaker": speaker, "vote": vote, "evidence": supporting})
        evidence.sort(key=lambda item: (item["date"], abs(item["stance"]), item["speaker"]), reverse=True)
        out.append({**aggregate, "name": names[ticker], "mentions": len(rows), "sources": len(by_speaker),
                    "last": max(row["date"] for row in rows), "items": evidence})
    by = {row["ticker"]: row for row in out}
    market = [{**by[ticker], "market_label": spec[0]} for ticker, spec in MARKET_LINES.items() if ticker in by]
    rows = sorted((row for row in out if row["ticker"] not in MARKET_LINES),
                  key=lambda row: (-row["sources"], -row["rank"], row["ticker"]))
    return {"as_of": today.isoformat(), "rows": rows, "market": market, "days": MAX_AGE_DAYS}


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
