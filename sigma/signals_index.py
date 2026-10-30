"""The Signals index: one JSON file per day with every Signals signal, for agents (docs/PRODUCT-DIRECTION.md, priority 1).

    sigma signals-index D          published/signals/D.json and published/signals/index.json

A signal is one stance label (stance.py) other than 0, from the day's podcast run (published/D/claims.jsonl, scored 4+) or
the day's X scan (published/x/stances/D.jsonl). The index copies no post text and no claim text: a row carries Sigma's own
reason (under 15 words), the speaker, a link to the moment (a podcast timestamp, an X post) and the fields a grader needs.

Each row names a `ticker` (or a market target, @MARKET), the `target` in words, a `direction` (bullish, bearish), a
`horizon_days` (5, 21 or 63 trading days) and an `origin` (primary: the speaker is first-hand, an operator, a data source or
giving their own view; recap: relaying news or someone else's view). The reader's own `origin` and `horizon_days` on the
label win; where there is none a default fills it and the row lists the field in `inferred`, so a grader can tell a
reader's horizon from ours. `complete: false` names each source that was not there or not fully labelled; the file is written
anyway and rebuilt by a later run. Rebuilding changes only what the sources changed: it is deterministic.

Standard library only at import, like stance.py: the site host copies the files and builds with nothing else.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from . import signals_sentiment, board, stance, tickers
from .paths import data_root
from .publication_policy import MIN_SCORE

ROOT = Path(__file__).resolve().parent.parent
DATA = data_root()
PUBLISHED = DATA / "published"
SCHEMA_VERSION = 1
HORIZONS = (5, 21, 63)       # trading days: the ledger grades a call at each
HOSTS = {"host", "co-host", "cohost", "hosts", "anchor", "interviewer", "narrator"}
# a role that is first-hand for the company it talks about
OPERATOR = re.compile(r"\b(ceo|cfo|cto|coo|founder|co-?founder|president|chair(man|woman)?|chief|head of|vp|general partner|portfolio manager)\b", re.I)
X_RECAP_TYPES = {"news"}     # a type of X account that mostly relays headlines
X_SHORT_TYPES = {"calls"}    # a dated call on a name: graded soonest
SNOWFLAKE_EPOCH_MS = 1288834974657


class SignalsError(ValueError):
    pass


def signals_dir(published: Path = PUBLISHED) -> Path:
    return Path(published) / "signals"


def post_time(post_id, tz=None) -> str:
    """When a post was made, from its id (X ids carry the time), as ISO 8601 in Pacific time."""
    ms = (int(post_id) >> 22) + SNOWFLAKE_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz or board.pacific_tz()).isoformat(timespec="seconds")


def _row_id(key: str, ticker: str) -> str:
    return "a-" + hashlib.sha1(f"{key}|{ticker}".encode()).hexdigest()[:12]


def _names(us: dict) -> dict:
    return {**us, **{t: line[1] for t, line in board.MARKET_LINES.items()}}


def _roles(published: Path, run: str) -> dict[str, str]:
    """speaker name -> role, from the run's selected guests and from people.yaml."""
    out: dict[str, str] = {}
    try:
        for e in json.loads((Path(published) / run / "selected.json").read_text(encoding="utf-8")).get("episodes") or []:
            for g in e.get("guests") or []:
                if isinstance(g, dict) and g.get("name") and g.get("role"):
                    out.setdefault(g["name"].lower(), g["role"])
    except (OSError, ValueError):
        pass
    try:
        from . import people

        for p in people.load_people(DATA / "people.yaml"):
            if p.role:
                out.setdefault(p.name.lower(), p.role)
    except Exception:  # no yaml parser on the site host, or no file: the selected guests are enough
        pass
    return out


def _x_accounts() -> dict[str, dict]:
    try:
        rows = json.loads((DATA / "x-accounts.json").read_text(encoding="utf-8")).get("accounts") or []
    except (OSError, ValueError):
        return {}
    return {str(a["handle"]).lower(): a for a in rows if isinstance(a, dict) and a.get("handle")}


def _origin_podcast(speaker: str, role: str) -> str:
    if not speaker or speaker.lower() in HOSTS or role.lower() in HOSTS:
        return "recap"
    return "primary" if role and role != "unknown" else "recap"


def _horizon_podcast(origin: str, role: str) -> int:
    return 63 if origin == "primary" and OPERATOR.search(role) else 21


def _pick(lab: dict, field: str, default, ok) -> tuple:
    """(value, inferred): the reader's value when it is valid, else the default."""
    v = lab.get(field)
    return (v, False) if ok(v) else (default, True)


def _row(*, key, date_, lab, names, speaker, role, link, source_kind, source_id, source_name, origin_d, horizon_d, **extra) -> dict:
    origin, o_inf = _pick(lab, "origin", origin_d, lambda v: v in ("primary", "recap"))
    horizon, h_inf = _pick(lab, "horizon_days", horizon_d, lambda v: v in HORIZONS)
    tk = lab["ticker"]
    target = " ".join(str(lab.get("target") or "").split()) or names.get(tk) or tk
    return {"id": _row_id(key, tk), "date": date_, "ticker": tk, "target": target[:80],
            "direction": "bullish" if lab["stance"] > 0 else "bearish", "stance": lab["stance"],
            "speaker": speaker, "role": role, "link": link, "source_kind": source_kind, "source_id": str(source_id),
            "source_name": source_name, "origin": origin, "horizon_days": horizon, "reason": lab["reason"],
            **extra, **({"inferred": [f for f, i in (("origin", o_inf), ("horizon_days", h_inf)) if i]} if o_inf or h_inf else {})}


def _podcast_runs(published: Path, day: str) -> list[Path]:
    root = Path(published)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and
                  (p.name == day or p.name.startswith(day + "-")) and (p / "claims.jsonl").is_file())


def _influencer_scores(runs: list[Path]) -> dict[str, tuple[str, object]]:
    out = {}
    for run in runs:
        try:
            rows = json.loads((run / "scores-influencer.json").read_text(encoding="utf-8")).get("episodes") or []
        except (OSError, ValueError):
            continue
        for row in rows:
            episode_id = row.get("episode_id")
            if not episode_id:
                continue
            owner_score = (row.get("scored_in") or run.name, row.get("score"))
            if episode_id in out and out[episode_id] != owner_score:
                raise SignalsError("a creator episode has conflicting scores in this publication date")
            out[episode_id] = owner_score
    return out


def podcast_rows(published: Path, day: str, labels: dict, names: dict, us: dict,
                 influencer_scores: dict[str, tuple[str, object]] | None = None) -> tuple[list[dict], int]:
    """(rows, stance items without a label) for run `day`. A stance item is a claim that names a US ticker or reads like a
    market view (stance.claim_items); the rest of the claims are never labelled."""
    rows_in = stance.read_jsonl(Path(published) / day / "claims.jsonl")
    if not rows_in:
        return [], 0
    influencer_scores = influencer_scores if influencer_scores is not None else _influencer_scores([Path(published) / day])
    from .site import publication_date

    roles, out, seen, unlabelled = _roles(published, day), [], set(), 0
    for c in rows_in:
        episode_id = c.get("episode_id")
        score_owner = influencer_scores.get(episode_id)
        influencer = score_owner is not None
        if influencer and score_owner[0] != day:
            continue
        score = score_owner[1] if influencer else c.get("score")
        if (influencer and not (isinstance(score, (int, float)) and score >= MIN_SCORE)) or (
                not influencer and c.get("source") != "report" and
                not (isinstance(score, (int, float)) and score >= MIN_SCORE)):
            continue
        key = stance.claim_key(c.get("episode_id"), c.get("timestamp"), c.get("text"))
        if key in seen:
            continue
        seen.add(key)
        if key not in labels:
            unlabelled += bool(stance.claim_items([c], us))
            continue
        speaker = str(c.get("speaker") or "").strip()
        kind = "youtube" if influencer else "podcast"
        role = roles.get(speaker.lower())
        if not role:  # no stated role: a creator on their own channel, a guest named in the title, a host, or unknown
            role = ("creator" if kind == "youtube" and speaker else "guest" if speaker and speaker.lower() in str(c.get("title") or "").lower()
                    else speaker.lower() if speaker.lower() in HOSTS else "unknown")
        ts = c.get("timestamp")
        link = c.get("link") or c.get("youtube_url") or c.get("url") or ""
        origin = _origin_podcast(speaker, role)
        for lab in labels[key]:
            if not lab.get("stance"):
                continue
            out.append(_row(key=key, date_=publication_date(c.get("published") or c.get("date") or day), lab=lab, names=names,
                            speaker=speaker or "unknown", role=role, link=link,
                            source_kind=kind,
                            source_id=c.get("episode_id"), source_name=c.get("show") or "", origin_d=origin,
                            horizon_d=_horizon_podcast(origin, role),
                            **({"timestamp_s": int(ts)} if isinstance(ts, (int, float)) else {})))
    return out, unlabelled


def x_rows(published: Path, day: str, labels: dict, names: dict) -> list[dict]:
    accounts, out, seen = _x_accounts(), [], set()
    in_thread = {i for ids in stance.threads_recorded(published).values() for i in ids}
    for r in stance.read_jsonl(Path(published) / "x" / "stances" / f"{day}.jsonl"):
        handle, pid = str(r.get("handle") or ""), str(r.get("id") or "")
        if not (board.HANDLE.fullmatch(handle) and pid.isdigit()) or r["key"] in seen or pid in in_thread or r["key"] not in labels:
            continue
        seen.add(r["key"])
        acct = accounts.get(handle.lower()) or {}
        typ = acct.get("type") or "unknown"
        for lab in labels[r["key"]]:
            if not lab.get("stance"):
                continue
            out.append(_row(key=r["key"], date_=str(r["date"])[:10], lab=lab, names=names, speaker="@" + handle,
                            role=f"X account, {typ}", link=f"https://x.com/{handle}/status/{pid}", source_kind="x",
                            source_id=pid, source_name="@" + handle, origin_d="recap" if typ in X_RECAP_TYPES or typ == "unknown" else "primary",
                            horizon_d=5 if typ in X_SHORT_TYPES else 21, posted_at=post_time(pid)))
    return out


def x_neutral(published: Path, day: str, labels: dict) -> dict[str, set]:
    """{ticker: speakers} for the day's X posts labelled 0 (a mention with no call): the index leaves them out as signals, the
    per-ticker aggregate (signals_sentiment.py) counts them as neutral."""
    in_thread = {i for ids in stance.threads_recorded(published).values() for i in ids}
    out: dict[str, set] = {}
    for r in stance.read_jsonl(Path(published) / "x" / "stances" / f"{day}.jsonl"):
        handle, pid = str(r.get("handle") or ""), str(r.get("id") or "")
        if not (board.HANDLE.fullmatch(handle) and pid.isdigit()) or pid in in_thread or r["key"] not in labels:
            continue
        for lab in labels[r["key"]]:
            if lab.get("stance") == 0:
                out.setdefault(lab["ticker"], set()).add("@" + handle)
    return out


def sentiment(signals: list[dict], neutral: dict[str, set] | None = None) -> dict:
    """`tickers` and `markets`: the day's X signals added up per ticker and per market target (signals_sentiment.py)."""
    signed: dict[str, set] = {}
    for r in signals:
        signed.setdefault(r["ticker"], set()).add(r["speaker"])
    flat = {t: len(who - signed.get(t, set())) for t, who in (neutral or {}).items()}
    return {"tickers": signals_sentiment.aggregate(signals, flat), "markets": signals_sentiment.aggregate(signals, flat, market=True)}


def _x_unlabelled(published: Path, day: str, labels: dict, us: dict) -> int | None:
    """Scanned posts of `day` with no label, or None when this machine has no scan (the site host)."""
    from . import entities, xdaily

    sd = xdaily.scan_dir(day)
    if not (sd / "posts.jsonl").exists():
        return None
    names = {str(n).lower(): c["ticker"] for c in entities.load().companies.values() if c.get("ticker")
             for n in [c.get("name"), *(c.get("aliases") or [])] if n and len(str(n)) >= 4 and not stance.reads_market(n)}
    items = stance.post_items(xdaily.read_jsonl(sd / "posts.jsonl"), {q["id"]: q for q in xdaily.read_jsonl(sd / "quoted.jsonl")}, us, names)
    return sum(1 for it in items if it["key"] not in labels)


def build(day: str, published: Path = PUBLISHED, us: dict | None = None, now: datetime | None = None) -> dict:
    """The day's index document. Never raises for a missing source: it says what is missing."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise SignalsError(f"{day!r} is not a date (YYYY-MM-DD)")
    published = Path(published)
    us = tickers.load() if us is None else us
    names, labels = _names(us), stance.labelled(published)
    missing = []
    run_dir = published / day
    runs = _podcast_runs(published, day)
    if not runs:
        if d.weekday() < 5:  # the daily issue is a weekday run; a weekend has no podcast source to wait for
            missing.append({"source": "podcast", "reason": f"no run published for {day}"})
        pod, unl = [], 0
    else:
        creator_scores = _influencer_scores(runs)
        podcast_by_id = {}
        unl = 0
        for run in runs:
            rows, count = podcast_rows(published, run.name, labels, names, us, creator_scores)
            unl += count
            for row in rows:
                old = podcast_by_id.get(row["id"])
                if old is None or (row["source_kind"] == "youtube" and old["source_kind"] != "youtube"):
                    podcast_by_id[row["id"]] = row
        pod = list(podcast_by_id.values())
        if unl:
            missing.append({"source": "podcast", "reason": f"{unl} claims of run {day} have no stance label yet"})
    if not (published / "x" / "stances" / f"{day}.jsonl").exists():
        missing.append({"source": "x", "reason": f"no X stance labels for {day}"})
        xs = []
    else:
        xs = x_rows(published, day, labels, names)
        left = _x_unlabelled(published, day, labels, us)
        if left:
            missing.append({"source": "x", "reason": f"{left} scanned posts of {day} have no stance label yet"})
    signals = sorted(pod + xs, key=lambda r: (-abs(r["stance"]), r["origin"] != "primary", r["ticker"], r["id"]))
    now = now or datetime.now(board.pacific_tz())
    neutral = x_neutral(published, day, labels) if (published / "x" / "stances" / f"{day}.jsonl").exists() else {}
    return {"schema_version": SCHEMA_VERSION, "date": day, "generated_at": now.isoformat(timespec="minutes"),
            "complete": not missing, "missing": missing,
            "counts": _counts(signals),
            **sentiment(signals, neutral),
            "signals": signals}


def write_index(published: Path = PUBLISHED) -> Path:
    """published/signals/index.json: every day's file, newest first."""
    ad = signals_dir(published)
    days = []
    for f in sorted(ad.glob("????-??-??.json"), reverse=True):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        days.append({"date": doc["date"], "path": f"/signals/{f.name}", "signals": doc["counts"]["signals"],
                     "complete": doc["complete"], "generated_at": doc["generated_at"]})
    p = ad / "index.json"
    p.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "about": "One file per day with every Signals signal. Schema: /signals/schema.json. Newest first.",
                             "days": days}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _counts(signals: list[dict]) -> dict:
    return {"signals": len(signals), "podcast": sum(r["source_kind"] != "x" for r in signals),
            "x": sum(r["source_kind"] == "x" for r in signals), "primary": sum(r["origin"] == "primary" for r in signals),
            "recap": sum(r["origin"] == "recap" for r in signals)}


def prune(published: Path, gone: set[str], affected_days=()) -> int:
    """Refresh existing Signals docs from surviving labels and scans after X deletion; return confirmed gone X rows."""
    published = Path(published)
    days = set(affected_days)
    docs = sorted(signals_dir(published).glob("????-??-??.json"))
    for f in docs:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(r.get("source_kind") == "x" and str(r.get("source_id")) in gone for r in doc.get("signals") or []):
            days.add(f.stem)
    removed, changed = 0, False
    for day in sorted(days):
        f = signals_dir(published) / f"{day}.json"
        if not f.is_file():
            continue
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
            generated = datetime.fromisoformat(old["generated_at"])
            current = build(day, published, now=generated)
        except (KeyError, OSError, TypeError, ValueError):
            raise SignalsError(f"cannot refresh the existing Signals document for {day}") from None
        if check(current, published):
            raise SignalsError(f"the refreshed Signals document for {day} fails validation")
        removed += sum(1 for r in old.get("signals") or []
                       if r.get("source_kind") == "x" and str(r.get("source_id")) in gone)
        if old != current:
            f.write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            changed = True
    if changed:
        write_index(published)
    return removed


def check(doc: dict, published: Path = PUBLISHED) -> list[str]:
    """Problems with a document: the schema, a gradable row without target, direction or horizon, copied words, and (when
    `published` holds the labels) an X row whose post was pruned."""
    import jsonschema

    from . import xdaily
    from .ranked import private_hits

    schema = json.loads((ROOT / "schema" / "signals-index.schema.json").read_text(encoding="utf-8"))
    try:
        jsonschema.validate(doc, schema)
    except jsonschema.ValidationError as exc:
        return [f"schema: {exc.message} at {'/'.join(map(str, exc.path))}"]
    problems = []
    ids = [r["id"] for r in doc["signals"]]
    if len(ids) != len(set(ids)):
        problems.append("a signal id repeats")
    if doc["complete"] == bool(doc["missing"]):
        problems.append("`complete` must be false exactly when `missing` names a source")
    for r in doc["signals"]:
        if len(r["reason"].split()) > stance.MAX_REASON_WORDS:
            problems.append(f"{r['id']}: the reason is over {stance.MAX_REASON_WORDS} words")
        if r["source_kind"] == "x" and "posted_at" not in r:
            problems.append(f"{r['id']}: an X row needs posted_at")
        if r["source_kind"] != "x" and not r["link"]:
            problems.append(f"{r['id']}: no link")
    for r in [*doc.get("tickers", []), *doc.get("markets", [])]:
        if len(r["reason"].split()) > 2 * stance.MAX_REASON_WORDS + 8:
            problems.append(f"{r['ticker']}: the aggregate reason is too long")
        if not set(r["signal_ids"]) <= set(ids):
            problems.append(f"{r['ticker']}: the aggregate names a signal the day does not have")
    if hits := private_hits([doc["signals"], doc.get("tickers", []), doc.get("markets", [])]):
        problems.append(f"the rows look private: {hits}")
    return problems


def signals_index_cmd(args) -> None:
    from . import events

    published = Path(args.published)
    days = [args.date] if args.date else []
    if args.all:
        days = sorted(p.stem for p in signals_dir(published).glob("????-??-??.json"))
    if not days:
        sys.exit("[signals-index] give a date (YYYY-MM-DD) or --all")
    signals_dir(published).mkdir(parents=True, exist_ok=True)
    bad = 0
    for day in days:
        try:
            doc = build(day, published)
        except SignalsError as exc:
            sys.exit(f"[signals-index] {exc}")
        probs = check(doc, published)
        for p in probs:
            print(f"[signals-index] {day}: {p}", file=sys.stderr)
        if probs:
            bad += 1
            continue
        (signals_dir(published) / f"{day}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        c = doc["counts"]
        mixed = [r["ticker"] for r in doc["tickers"] if r["label"] == "Mixed"]
        print(f"[signals-index] {day}: {len(doc['tickers'])} X tickers aggregated" + (f", Mixed: {', '.join(mixed)}" if mixed else ""))
        print(f"[signals-index] {day}: {c['signals']} signals ({c['podcast']} podcast, {c['x']} X; {c['primary']} primary, {c['recap']} recap); "
              + ("complete" if doc["complete"] else "INCOMPLETE: " + "; ".join(f"{m['source']}: {m['reason']}" for m in doc["missing"])))
        events.note(signals=c["signals"], complete=doc["complete"])
    write_index(published)
    if bad:
        sys.exit(f"[signals-index] {bad} day(s) not written: fix the problems above")
