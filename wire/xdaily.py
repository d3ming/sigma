"""The daily X edition: a scanner writes the day's posts, an editor agent writes cited blurbs, Wire checks and publishes them.

Any agent can run it. The scanner (an agent reading X through the official API) follows `skills/x-scan/SKILL.md` and writes
`<x dir>/scan/<date>/` (manifest.json, posts.jsonl, quoted.jsonl; `schema/x-scan.schema.json`). The editor follows
`prompts/x-daily.md`. `wire x status` names the next step. The x dir is `data/x` unless WIRE_X_DIR points elsewhere; it
is private, because it holds post text. Only ids, handles, cashtags and Wire's own sentences reach `published/x/editions/`.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema"
PREP_KEEP = 150          # Alpha posts the editor reads
MORE = {"alpha": 30, "si": 15}  # top-ranked posts the editor did not list, shown under "More from today"
LONG_CHARS, LONG_KEEP = 1000, 40  # a write-up this long, or a focus match, reaches the editor below the cut: up to LONG_KEEP more per lens
SI_KEEP = 80             # SI posts the editor reads: ranked apart from Alpha, so cashtag-heavy accounts never crowd them out
# Ranking signals besides engagement against the author's own median (a high repost ratio, saves and
# likes say whether a post has signal). Each ratio term is log1p(RATIO_SCALE * ratio), capped at RATIO_CAP.
RATIO_W = 1.0            # weight of (reposts + quotes) / (likes + 5)
SAVES_W = 2.0            # weight of bookmarks / (likes + 5): saves best marked the posts a reader kept
RATIO_SCALE = 10
RATIO_CAP = 1.5
AGE_REF_H = 12           # age adjustment: a post younger than this is scaled up toward what it will have collected
AGE_FLOOR_H = 2          # ... counting any post as at least this old
AGE_EXP = 0.5
# SI's first job is how to work with the agents the owner uses: posts naming them rank higher
SI_FOCUS = re.compile(r"claude code|\bcodex\b|\bgrok\b|\bmuse\b", re.I)
# Alpha's lift: someone showing what they actually did with real money (a trade, a position, a portfolio update), which the owner
# values far above news (2026-10-28). Loose on purpose: the editor judges each post.
ALPHA_FOCUS = re.compile(r"\b(i|we)(\s+(just|also|finally))?\s+(bought|sold|added|trimmed|exited|opened|closed|shorted|sized|took profits?)\b"
                         r"|\bmy (portfolio|positions?|holdings|book)\b|\b(starter|new|full|core|open) position\b|\bposition size\b"
                         r"|\b(added to|trimmed|sold out of|exited|initiated)\s+(my\s+)?\$[A-Za-z]{1,5}\b|\bportfolio (update|performance)\b", re.I)
MAX_SI_ACCOUNTS = 45     # core SI accounts. 2026-10-27's scan read 105 accounts (75 Alpha, 30 SI) in 74 calls with no rate limit, Alpha first
QUOTE_WORDS = 12         # a run this long copied from a post is a quote, which the edition may not carry
MAX_WINDOW_HOURS = 72    # a scan never reaches further back than this


def x_dir() -> Path:
    """$WIRE_X_DIR, else the first of `data/x` and `../darkroom/wire/x` (a darkroom clone next to this one, where the scanner
    keeps its clones) that exists, else `data/x`."""
    if env := os.environ.get("WIRE_X_DIR"):
        return Path(env)
    return next((c for c in (ROOT / "data" / "x", ROOT.parent / "darkroom" / "wire" / "x") if c.is_dir()), ROOT / "data" / "x")


def scan_dir(d: str) -> Path:
    return x_dir() / "scan" / d


def day_dir(d: str) -> Path:
    return x_dir() / "days" / d


def edition_path(published: Path, d: str) -> Path:
    return Path(published) / "x" / "editions" / f"{d}.json"


def read_jsonl(p: Path) -> list[dict]:
    # split on "\n" only: splitlines() also breaks on U+2028, which JSON allows raw inside a string
    return [json.loads(line) for line in p.read_text(encoding="utf-8").split("\n") if line.strip()] if p.exists() else []


ACCOUNTS = ROOT / "x-accounts.json"  # public: who the scan reads; changes by pull request, approved by the owner


# What kind of posts an account gives, per lens (what each type means: the `note` in x-accounts.json). `type` is the main kind;
# `type2` is optional and set only when about a quarter or more of the account's posts are of that second kind. The type reaches
# the editor as `@handle [howto]` or `[howto/ai-news]` in prep.md. A missing or unknown type, or one from the other lens, makes
# accounts() raise, `wire x scan-check` report it and `wire doctor` fail its x check.
ACCOUNT_TYPES = {"alpha": ("calls", "analysis", "data", "macro", "news"), "si": ("howto", "ai-news", "ai-research")}


def account_problems(rows: list[dict]) -> list[str]:
    """What is wrong with the account list: a lens that is not alpha or si, a missing or unknown `type`, a `type2` that is
    unknown or repeats `type`. Each type must belong to the account's own lens."""
    out = []
    for a in rows:
        lens, h = a.get("lens") or "alpha", a.get("handle", "?")
        if lens not in ACCOUNT_TYPES:
            out.append(f"@{h}: lens {lens!r} is not one of {', '.join(ACCOUNT_TYPES)}")
            continue
        for key in ("type", "type2"):
            if key == "type2" and "type2" not in a:
                continue
            if a.get(key) not in ACCOUNT_TYPES[lens]:
                out.append(f"@{h}: {key} {a.get(key)!r} is not one of {', '.join(ACCOUNT_TYPES[lens])} (lens {lens})")
        if a.get("type2") and a.get("type2") == a.get("type"):
            out.append(f"@{h}: type2 repeats type")
    return out


def accounts(path: Path | None = None) -> list[dict]:
    """The account list. A list with an unknown or missing type raises ValueError naming the bad entries."""
    p = path or ACCOUNTS
    rows = json.loads(p.read_text(encoding="utf-8")).get("accounts", []) if p.exists() else []
    if bad := account_problems(rows):
        raise ValueError(f"{p.name}: " + "; ".join(bad[:10]) + (f"; and {len(bad) - 10} more" if len(bad) > 10 else ""))
    return rows


# ---------------------------------------------------------------- scan check

SCAN_SKILL = ROOT / "skills" / "x-scan" / "SKILL.md"


def contract_version() -> int:
    """The scan contract's version: `contract_version:` in skills/x-scan/SKILL.md's front matter. A scanner copies it into
    its manifest; bump it when the scan format or rules change in a way the scanner must act on."""
    head = SCAN_SKILL.read_text(encoding="utf-8").split("---")[1] if SCAN_SKILL.exists() else ""
    m = re.search(r"^contract_version:\s*(\d+)\s*$", head, re.M)
    if not m:
        raise ValueError(f"{SCAN_SKILL.name} has no contract_version in its front matter")
    return int(m.group(1))


def scan_problems(d: str, contract: bool = False) -> list[str]:
    """Why the scan for date d cannot be used, or [] when it can. The scanner runs this before delivering. With `contract`
    (`wire x scan-check`, the scanner's delivery check) the manifest must carry the skill's current contract_version; readers
    leave it off, so an older scan stays usable after the contract moves on."""
    sd = scan_dir(d)
    if not (sd / "manifest.json").exists():
        hint = "" if os.environ.get("WIRE_X_DIR") else "; WIRE_X_DIR is not set and neither data/x nor ../darkroom/wire/x exists: point it at <darkroom clone>/wire/x"
        return [f"no manifest: {sd}/manifest.json (the scanner writes it last){hint}"]
    schema = json.loads((SCHEMA / "x-scan.schema.json").read_text())
    out = []
    try:
        man = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
        jsonschema.validate(man, {**schema["$defs"]["manifest"], "$defs": schema["$defs"]})
    except (ValueError, jsonschema.ValidationError) as e:
        return [f"manifest.json: {getattr(e, 'message', e)}"]
    if man["date"] != d:
        out.append(f"manifest date {man['date']} is not {d}")
    if contract and man.get("contract_version") != (want := contract_version()):
        out.append(f"manifest contract_version is {man.get('contract_version')!r}; skills/x-scan/SKILL.md is at {want}"
                   " (re-read the skill, follow it, and set contract_version in the manifest)")
    if not man["complete"]:
        out.append(f"scan incomplete: {man['accounts_ok']}/{man['accounts_requested']} accounts ok"
                   + (", rate limited" if man["rate_limited"] else ""))
    start, end = (datetime.fromisoformat(man[k].replace("Z", "+00:00")) for k in ("window_start", "window_end"))
    if not timedelta(hours=1) <= end - start <= timedelta(hours=MAX_WINDOW_HOURS):
        out.append(f"window is {end - start}; it must be 1 to {MAX_WINDOW_HOURS} hours")
    try:
        accounts()  # a post by a handle that is no longer listed is not a problem: prep skips it (see prep_cmd)
    except ValueError as e:
        return [str(e)]
    post = {**schema["$defs"]["post"], "$defs": schema["$defs"]}
    seen = set()
    for name in ("posts.jsonl", "quoted.jsonl"):
        if not (sd / name).exists():
            out.append(f"missing {name} (write it empty when there is nothing)")
            continue
        for n, r in enumerate(read_jsonl(sd / name), 1):
            try:
                jsonschema.validate(r, post)
            except jsonschema.ValidationError as e:
                out.append(f"{name}:{n}: {e.message}")
                continue
            if name == "posts.jsonl":
                if r["id"] in seen:
                    out.append(f"{name}:{n}: duplicate id {r['id']}")
                seen.add(r["id"])
                t = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                if not start <= t <= end:
                    out.append(f"{name}:{n}: {r['created_at']} is outside the window")
    out += id_check_problems(d, man)
    return out[:40]


def id_check_problems(d: str, man: dict) -> list[str]:
    """The deletion check (wire/xprune.py): when the list the scanner was given (check-ids.json, written before this
    scan, so its `through` is before d) has ids, the manifest must say how many it checked and which are gone. A list
    written after this scan's edition (`through` d or later) is a newer one: nothing to compare."""
    try:
        lst = json.loads((x_dir() / "check-ids.json").read_text(encoding="utf-8"))
        ids, through = {str(i) for i in lst["ids"]}, str(lst["through"])
    except (OSError, ValueError, KeyError, TypeError):
        ids, through = set(), d
    gone = set(map(str, man.get("ids_gone") or []))
    out = []
    if ids and through < d:
        if not isinstance(man.get("ids_checked"), int) or not isinstance(man.get("ids_gone"), list):
            out.append(f"manifest: check-ids.json lists {len(ids)} ids; report ids_requested, ids_checked and ids_gone (skills/x-scan, step 7)")
        elif man.get("ids_requested") != len(ids):
            out.append(f"manifest: ids_requested is {man.get('ids_requested')} but check-ids.json lists {len(ids)}")
        if stray := sorted(gone - ids):
            out.append(f"manifest: ids_gone has ids that were not in check-ids.json: {', '.join(stray[:3])}")
    if man.get("ids_checked", 0) > man.get("ids_requested", 0):
        out.append("manifest: ids_checked is more than ids_requested")
    if len(gone) > man.get("ids_checked", 0):
        out.append("manifest: more ids_gone than ids_checked")
    return out


def coverage_warnings(d: str) -> list[str]:
    """Per-account gaps in a valid scan that are not errors: a scan can be complete and still miss an account. Core accounts of
    x-accounts.json with no post in the window (a quiet day, or a search that never returned them), accounts whose every post is
    a reply to someone else (the skill drops those, so the account's own posts were not returned: a handle like `bot` that the
    search matches as a word), and a manifest that requested fewer accounts than the list has."""
    sd = scan_dir(d)
    try:
        man = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
        core = [a["handle"].lower() for a in accounts() if a.get("tier") == "core"]
    except (OSError, ValueError, KeyError):
        return []
    failed = {str(f.get("handle", "")).lower().lstrip("@") for f in man.get("accounts_failed", [])}
    own: dict[str, int] = {}
    replies: dict[str, int] = {}
    for p in read_jsonl(sd / "posts.jsonl"):
        h = str(p.get("handle", "")).lower()
        own[h] = own.get(h, 0) + 1
        if p.get("in_reply_to_id") and (p.get("in_reply_to_handle") or "").lower() != h:
            replies[h] = replies.get(h, 0) + 1
    out = []
    if (n := man.get("accounts_requested")) is not None and n < len(core):
        out.append(f"the manifest requested {n} accounts; x-accounts.json lists {len(core)} core accounts")
    quiet = [h for h in core if h not in own and h not in failed]
    if quiet:
        out.append(f"{len(quiet)} of {len(core)} core accounts have no post in the window: " + ", ".join("@" + h for h in quiet[:30])
                   + (f" and {len(quiet) - 30} more" if len(quiet) > 30 else ""))
    for h in core:
        if own.get(h) and replies.get(h) == own[h]:
            out.append(f"@{h}: all {own[h]} posts are replies to other people, so its own posts were probably not returned (search by author, not by word)")
    return out


def scan_check_cmd(args) -> None:
    probs = scan_problems(args.date, contract=True)
    for p in probs:
        print(f"[x] problem: {p}")
    if probs:
        raise SystemExit(1)
    for w in coverage_warnings(args.date):
        print(f"[x] warning: {w}")
    man = json.loads((scan_dir(args.date) / "manifest.json").read_text(encoding="utf-8"))
    print(f"[x] scan {args.date} ok: {len(read_jsonl(scan_dir(args.date) / 'posts.jsonl'))} posts"
          + (f"; {man['ids_checked']} of {man['ids_requested']} published ids checked, {len(man['ids_gone'])} gone"
             if "ids_checked" in man else ""))


# ---------------------------------------------------------------- heartbeat

HEARTBEAT_STAGES = ("scan", "edition")  # who beats: the scanner after each run (even a failed one), the editor after publishing
HEARTBEAT_MAX_HOURS = 26                # a nightly job plus slack for an on-demand run's drift


def heartbeat_path(stage: str) -> Path:
    return x_dir() / "heartbeat" / f"{stage}.json"


def heartbeat_cmd(args) -> None:
    """`wire x heartbeat <stage> --by NAME`: record that a stage ran, in <x dir>/heartbeat/<stage>.json (private darkroom data, one
    file per stage so the scanner's and the editor's clones never conflict). Commit and push it with the stage's other output."""
    p = heartbeat_path(args.stage)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"stage": args.stage, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "by": args.by, "date": args.date}
    p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    print(f"[x] heartbeat {args.stage}: {p}")


def health(now: datetime, max_hours: float = HEARTBEAT_MAX_HOURS) -> tuple[list[str], list[str]]:
    """(status lines, problems). A stage is stale when its newest signal is older than max_hours: the scan's is the later of its
    heartbeat and the newest manifest's window_end; the edition's is its heartbeat. It reads only the x dir, so any machine with
    a darkroom clone can ask whether the Mac, the scanner or the editor has gone quiet."""
    lines, probs = [], []
    for stage in HEARTBEAT_STAGES:
        seen: list[tuple[datetime, str]] = []
        try:
            hb = json.loads(heartbeat_path(stage).read_text(encoding="utf-8"))
            seen.append((_ts(hb["at"]), f"heartbeat from {hb.get('by') or 'unknown'}"))
        except (OSError, ValueError, KeyError):
            pass
        if stage == "scan":
            for m in sorted((x_dir() / "scan").glob("*/manifest.json")):
                try:
                    seen.append((_ts(json.loads(m.read_text(encoding="utf-8"))["window_end"]), f"scan {m.parent.name}"))
                except (OSError, ValueError, KeyError):
                    pass
        if not seen:
            lines.append(f"{stage}: no heartbeat")
            probs.append(f"{stage}: no heartbeat yet in {x_dir()}/heartbeat/")
            continue
        at, what = max(seen)
        age = (now - at).total_seconds() / 3600
        lines.append(f"{stage}: last signal {age:.1f} h ago ({what})")
        if age > max_hours:
            probs.append(f"{stage}: nothing for {age:.0f} h (limit {max_hours:g} h); last was {what}")
    return lines, probs


def health_cmd(args) -> None:
    lines, probs = health(datetime.now(timezone.utc), args.max_hours)
    for ln in lines:
        print(f"[x] {ln}")
    for p in probs:
        print(f"[x] stale: {p}")
    if probs:
        raise SystemExit(1)


def lens_by_handle() -> dict[str, str]:
    """handle (lower case) -> "alpha" or "si", from x-accounts.json. A handle it does not list reads as Alpha."""
    return {a["handle"].lower(): a.get("lens") or "alpha" for a in accounts()}


def type_by_handle() -> dict[str, str]:
    """handle (lower case) -> the account's type for the editor: "howto", or "howto/ai-news" with a second type."""
    return {a["handle"].lower(): "/".join(filter(None, (a.get("type"), a.get("type2")))) for a in accounts()}


# ---------------------------------------------------------------- prep

def is_noise(p: dict) -> bool:
    """Reposts, replies to other people, and one-liners with nothing attached never reach the editor."""
    if p.get("is_repost") or p["text"].startswith("RT @"):
        return True
    if p.get("in_reply_to_id") and (p.get("in_reply_to_handle") or "").lower() != p["handle"].lower():
        return True
    return len(p["text"]) < 40 and not p.get("media") and not p.get("quoted_id")


def engagement(p: dict) -> float:
    m = p.get("metrics") or {}
    return (m.get("like") or 0) + 2 * (m.get("repost") or 0) + 2 * (m.get("quote") or 0) + (m.get("bookmark") or 0)


def _metric(p: dict, key: str) -> int:
    return (p.get("metrics") or {}).get(key) or 0


def age_adjusted(p: dict, now: datetime | None) -> float:
    """Engagement as if the post had had AGE_REF_H hours: a post scanned 2 hours after it went up has not yet collected what
    it will, so it is scaled up by (AGE_REF_H / its age) ** AGE_EXP, with the age floored at AGE_FLOOR_H and the scale never
    below 1 (an old post is not marked down). The exponent is under 1 because most engagement arrives in the first hours."""
    e = engagement(p)
    if now is None:
        return e
    age_h = (now - _ts(p["created_at"])).total_seconds() / 3600
    return e * max(1.0, AGE_REF_H / max(age_h, AGE_FLOOR_H)) ** AGE_EXP


def rank_posts(posts: list[dict], keep: int = PREP_KEEP, focus: re.Pattern | None = None, now: datetime | None = None) -> list[dict]:
    """Best first. Core: age-adjusted engagement against the author's own median in this scan (so a small account's best post
    can beat a big account's routine one). Plus the signals that separate a post people pass on from one they only like: reposts
    and quotes per like, and saves (bookmarks) per like, each log-scaled and capped; a little for a cashtag and for length; and
    the lens's focus lift (ALPHA_FOCUS, SI_FOCUS). `now` is the scan's window_end, for the age adjustment. Deterministic; the editor does the judging."""
    adj = {p["id"]: age_adjusted(p, now) for p in posts}
    by_author: dict[str, list[float]] = {}
    for p in posts:
        by_author.setdefault(p["handle"].lower(), []).append(adj[p["id"]])
    for p in posts:
        med, e, likes = statistics.median(by_author[p["handle"].lower()]), adj[p["id"]], _metric(p, "like")
        share = (_metric(p, "repost") + _metric(p, "quote")) / (likes + 5)
        saves = _metric(p, "bookmark") / (likes + 5)
        p["_rank"] = round(math.log1p(e) - math.log1p(med) + 0.1 * math.log1p(e)
                           + RATIO_W * min(math.log1p(RATIO_SCALE * share), RATIO_CAP)
                           + SAVES_W * min(math.log1p(RATIO_SCALE * saves), RATIO_CAP)
                           + 0.5 * bool(p.get("cashtags")) + 0.3 * (len(p["text"]) > 280)
                           + 1.5 * bool(focus and focus.search(p["text"])), 3)
    ranked = sorted(posts, key=lambda p: (-p["_rank"], p["id"]))
    # Engagement ranks a small account's long, specific write-up near its own chatter, so it fell below the cut and the editor
    # never saw it (2026-10-27: a 3,200-character trading plan ranked 169th of 666). Long posts, and posts the focus matches
    # (a real trade, for Alpha), go to the editor anyway.
    return ranked[:keep] + [p for p in ranked[keep:]
                            if len(p["text"]) >= LONG_CHARS or (focus and focus.search(p["text"]))][:LONG_KEEP]


def prep_md(d: str, kept: dict[str, list[dict]], quoted: dict, total: int, types: dict[str, str] | None = None) -> str:
    """`kept` is lens -> its posts, best first; Alpha is written first, then SI. `types` is handle -> the account's type."""
    out = [f"# X scan {d}: {sum(map(len, kept.values()))} of {total} posts, best first within each lens", "",
           "Each post: id, @handle [the account's type], time (UTC), cashtags, likes/reposts/saves, media count. Cite ids exactly. "
           "An `alpha` sentence cites posts under Alpha, an `si` sentence posts under SI.", ""]
    for lens, name in (("alpha", "Alpha"), ("si", "SI")):
        out += [f"# {name}: {len(kept.get(lens, []))} posts", ""]
        for p in kept.get(lens, []):
            m = p.get("metrics") or {}
            kind = (types or {}).get(p["handle"].lower())
            head = (f"## {p['id']} @{p['handle']}{f' [{kind}]' if kind else ''} {p['created_at'][5:16].replace('T', ' ')}"
                    f" | {' '.join('$' + c for c in p.get('cashtags') or [])} | {m.get('like', 0)}♥ {m.get('repost', 0)}↻ {m.get('bookmark', 0)}🔖"
                    + (f" | {len(p['media'])} media (no figures from charts)" if p.get("media") else ""))
            out += [head, p["text"][:1500]]
            if q := quoted.get(p.get("quoted_id") or ""):
                out.append(f"> quoting @{q['handle']}: {q['text'][:600]}")
            out.append("")
    return "\n".join(out)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _window_end(path: Path, *keys) -> str | None:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        for k in keys:
            v = v[k]
        return str(v)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def prep_end(d: str) -> str | None:
    """The scan window_end `wire x prep` last read (days/<d>/prep.json). None before it ran or for a day prepped earlier."""
    return _window_end(day_dir(d) / "prep.json", "window_end")


def published_end(d: str, published: Path) -> str | None:
    """The scan window_end the published edition was built from: its own `window`."""
    return _window_end(edition_path(published, d), "window", 1)


def scan_is_newer(d: str, published: Path) -> bool:
    """True when the scan was extended (an on-demand scan, then the scheduled one) after the edition was built from it."""
    end, built = _window_end(scan_dir(d) / "manifest.json", "window_end"), prep_end(d) or published_end(d, published)
    return bool(end and built and _ts(built) < _ts(end))


def prep_cmd(args) -> None:
    probs = scan_problems(args.date)
    if probs:
        raise SystemExit("[x] the scan is not usable; no edition today:\n  " + "\n  ".join(probs))
    sd, dd = scan_dir(args.date), day_dir(args.date)
    window_end = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))["window_end"]
    if (dd / "edition.json").exists() and scan_is_newer(args.date, Path(args.published)):
        # the scan grew since this edition was written: the editor writes a new one (a published one stays in published/)
        (dd / "edition.json").unlink()
    posts = read_jsonl(sd / "posts.jsonl")
    quoted = {q["id"]: q for q in read_jsonl(sd / "quoted.jsonl")}
    lens = lens_by_handle()
    # a list change must never break a scan: posts from handles no longer listed (an old or extended scan) are skipped
    unlisted = [p for p in posts if lens and p["handle"].lower() not in lens]
    kept = ranked_day(args.date, args.keep)
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "prep.md").write_text(prep_md(args.date, kept, quoted, len(posts), type_by_handle()), encoding="utf-8")
    (dd / "prep.json").write_text(json.dumps({"date": args.date, "window_end": window_end, "posts": len(posts)}) + "\n", encoding="utf-8")
    if unlisted:
        who = sorted({p["handle"].lower() for p in unlisted})
        print(f"[x] skipped {len(unlisted)} posts by {len(who)} accounts no longer in x-accounts.json: {', '.join('@' + h for h in who)}")
    print(f"[x] {len(kept['alpha'])} Alpha and {len(kept['si'])} SI posts of {len(posts)} -> {dd / 'prep.md'}. Next: write {dd / 'edition.json'} per prompts/x-daily.md")


# ---------------------------------------------------------------- edition check

NUM = re.compile(r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:%|x|bn|b|m|k|B|M|K)?(?![\w])")


def norm_num(s: str) -> str:
    return re.sub(r"[$€£,\s]", "", s).lower().rstrip("x")


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9$%.']+", s.lower())


def copied_run(sentence: str, source: str, n: int = QUOTE_WORDS) -> str | None:
    """The first run of n words the sentence shares verbatim with the source, if any."""
    w, src = words(sentence), " " + " ".join(words(source)) + " "
    for i in range(len(w) - n + 1):
        run = " ".join(w[i:i + n])
        if f" {run} " in src:
            return run
    return None


def edition_problems(d: str, ed: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for an edition against its scan."""
    errs, warns = [], []
    try:
        jsonschema.validate(ed, json.loads((SCHEMA / "x-edition.schema.json").read_text()))
    except jsonschema.ValidationError as e:
        return [f"schema: {e.message} at {'/'.join(map(str, e.path))}"], []
    if ed["date"] != d:
        errs.append(f"date {ed['date']} is not {d}")
    sd = scan_dir(d)
    posts = {p["id"]: p for p in read_jsonl(sd / "posts.jsonl")}
    quoted = {q["id"]: q for q in read_jsonl(sd / "quoted.jsonl")}

    def text_of(pid: str) -> str:
        p = posts[pid]
        q = quoted.get(p.get("quoted_id") or "")
        return p["text"] + ("\n" + q["text"] if q else "")

    if not ed["alpha"]:
        errs.append("alpha: the edition needs at least one Alpha sentence")
    for lens in ("alpha", "si"):
        runs = [t for i, t in enumerate(s.get("theme") for s in ed.get(lens) or []) if i == 0 or t != (ed[lens][i - 1].get("theme"))]
        if any(runs.count(t) > 1 for t in runs if t):
            errs.append(f"{lens}: a theme's sentences must be consecutive")
        if len({bool(s.get("theme")) for s in ed.get(lens) or []}) > 1:
            errs.append(f"{lens}: give every sentence a theme, or none")
    lens_of_post = {p["id"]: p["lens"] for p in ed["posts"]}
    for lens in ("alpha", "si"):
        for n, s in enumerate(ed.get(lens) or [], 1):
            where = f"{lens} s{n}"
            missing = [c for c in s["cites"] if c not in posts]
            if missing:
                errs.append(f"{where}: cites {', '.join(missing)}, not in the scan")
                continue
            if wrong := [c for c in s["cites"] if lens_of_post.get(c, lens) != lens]:
                errs.append(f"{where}: cites {', '.join(wrong)}, listed under the {lens_of_post[wrong[0]]} lens in `posts`; cite posts from its own lens")
            cited = "\n".join(text_of(c) for c in s["cites"])
            have = {norm_num(m) for m in NUM.findall(cited)}
            for num in NUM.findall(s["text"]):
                k = norm_num(num)
                if len(re.sub(r"\D", "", k)) >= 2 or "%" in k or "$" in num:
                    if k not in have and k.rstrip("bmk%") not in {h.rstrip("bmk%") for h in have}:
                        media = any(posts[c].get("media") for c in s["cites"])
                        errs.append(f'{where}: "{num.strip()}" is not in the text of the cited posts'
                                    + (" (if it came from a chart: figures from charts are not allowed)" if media else ""))
            if run := copied_run(s["text"], cited):
                errs.append(f'{where}: copies {QUOTE_WORDS}+ words from a post ("{run[:60]}..."); paraphrase')
    seen = set()
    for p in ed["posts"]:
        if p["id"] not in posts:
            errs.append(f"posts: {p['id']} is not in the scan")
        if p["id"] in seen:
            errs.append(f"posts: {p['id']} listed twice")
        seen.add(p["id"])
    cited = {c for lens in ("alpha", "si") for s in ed.get(lens) or [] for c in s["cites"]}
    if cited - seen:
        warns.append(f"{len(cited - seen)} cited posts are not in `posts`, so readers cannot see them")
    return errs, warns


def check_cmd(args) -> None:
    p = day_dir(args.date) / "edition.json"
    if not p.exists():
        raise SystemExit(f"[x] no edition yet: {p}")
    errs, warns = edition_problems(args.date, json.loads(p.read_text(encoding="utf-8")))
    for w in warns:
        print(f"[x] warning: {w}")
    for e in errs:
        print(f"[x] error: {e}")
    if errs:
        raise SystemExit(f"[x] {len(errs)} errors: fix {p}, then run the check again")
    print(f"[x] edition {args.date} ok. Next: wire x publish {args.date}")


# ---------------------------------------------------------------- publish

def ranked_day(d: str, keep: int = PREP_KEEP) -> dict[str, list[dict]]:
    """lens -> the day's posts as prep ranks them for the editor, best first."""
    sd = scan_dir(d)
    end = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))["window_end"]
    lens = lens_by_handle()
    live = [p for p in read_jsonl(sd / "posts.jsonl") if not is_noise(p) and not (lens and p["handle"].lower() not in lens)]
    return {l: rank_posts([p for p in live if lens.get(p["handle"].lower(), "alpha") == l], n, focus, _ts(end))
            for l, n, focus in (("alpha", keep, ALPHA_FOCUS), ("si", SI_KEEP, SI_FOCUS))}


def public_edition(d: str, ed: dict) -> dict:
    """What the site gets: Wire's sentences, cited ids, and per post only id, handle, lens and cashtags. Never post text.
    `more` adds the top-ranked posts the editor did not list, so the page shows far more of the day than the editor cites."""
    sd = scan_dir(d)
    man = json.loads((sd / "manifest.json").read_text(encoding="utf-8"))
    posts = {p["id"]: p for p in read_jsonl(sd / "posts.jsonl")}
    listed = {p["id"] for p in ed["posts"]}
    card = lambda p, l: {"id": p["id"], "handle": p["handle"], "lens": l, "date": p["created_at"][:10], "cashtags": p.get("cashtags") or []}
    more = [card(p, l) for l, ps in ranked_day(d).items() for p in [p for p in ps if p["id"] not in listed][:MORE[l]]]
    return {"date": d, "window": [man["window_start"], man["window_end"]], "accounts": man["accounts_ok"],
            "posts_read": len(posts), "headline": ed.get("headline") or "",
            "alpha": ed["alpha"], "si": ed.get("si") or [],
            "posts": [{"id": p["id"], "handle": posts[p["id"]]["handle"], "lens": p["lens"],
                       "date": posts[p["id"]]["created_at"][:10], "cashtags": posts[p["id"]].get("cashtags") or []}
                      for p in ed["posts"]],
            "more": more}


def publish_cmd(args) -> None:
    p = day_dir(args.date) / "edition.json"
    ed = json.loads(p.read_text(encoding="utf-8"))
    errs, _ = edition_problems(args.date, ed)
    if errs:
        raise SystemExit(f"[x] the edition fails its check ({len(errs)} errors); run wire x check {args.date}")
    from .ranked import private_hits

    public = public_edition(args.date, ed)
    if hits := private_hits(json.dumps(public, ensure_ascii=False)):
        raise SystemExit(f"[x] the edition looks private ({hits}); rewrite those sentences")
    out = edition_path(Path(args.published), args.date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(public, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[x] published {out}. Next: git add {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} && commit and push")


# ---------------------------------------------------------------- status

def _pushed(path: Path) -> bool:
    """True when path is committed, unchanged, and on origin/develop, so a second run stops instead of redoing the day."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", *a], cwd=path.parent, capture_output=True, text=True)
    try:
        return (git("status", "--porcelain", "--", path.name).stdout == "" and git("ls-files", "--error-unmatch", path.name).returncode == 0
                and git("diff", "--quiet", "origin/develop", "--", path.name).returncode == 0)
    except OSError:
        return False


def status(d: str, published: Path) -> dict:
    """Where the day stands and the one next step, for any agent."""
    sd, dd = scan_dir(d), day_dir(d)
    st = {"date": d, "x_dir": str(x_dir()), "scan": "missing", "prep": "missing", "edition": "missing", "published": False}
    if (sd / "manifest.json").exists():
        probs = scan_problems(d)
        st["scan"], st["scan_problems"] = ("ready", []) if not probs else ("unusable", probs)
    st["prep"] = "done" if (dd / "prep.md").exists() else "missing"
    st["scan_newer"] = st["scan"] == "ready" and scan_is_newer(d, published)
    if st["scan_newer"]:
        st["prep"] = "stale"
    if (dd / "edition.json").exists():
        try:
            errs, _ = edition_problems(d, json.loads((dd / "edition.json").read_text(encoding="utf-8")))
        except ValueError as e:
            errs = [f"not JSON: {e}"]
        st["edition"], st["edition_errors"] = ("ok", []) if not errs else ("failing", errs)
    st["published"] = edition_path(published, d).exists()
    if st["published"] and (pe := prep_end(d)) and (pub := published_end(d, published)) and _ts(pub) < _ts(pe):
        st["published"] = False  # the edition was rebuilt from a longer scan; the published file is still the old one
    if st["scan"] == "missing":
        nxt = {"type": "stop", "summary": f"No scan for {d}. The scanner (skills/x-scan) has not delivered: report it; there is no fallback."}
    elif st["scan"] == "unusable":
        nxt = {"type": "stop", "summary": "The scan fails its check: report the problems to the scanner's owner; no edition today."}
    elif st["prep"] in ("missing", "stale"):
        nxt = {"type": "command", "command": f"wire x prep {d}"}
        if st["published"]:
            nxt["summary"] = f"The scan grew after the edition for {d} was built: rebuild it. Prep removes the old days edition.json; the published one stays until you publish."
    elif st["edition"] != "ok":
        nxt = {"type": "agent", "prompt": "prompts/x-daily.md", "input": str(dd / "prep.md"), "output": str(dd / "edition.json"),
               "then": f"wire x check {d}"}
    elif not st["published"]:
        nxt = {"type": "command", "command": f"wire x publish {d}"}
    elif _pushed(edition_path(published, d)):
        nxt = {"type": "done", "pushed": True, "summary": f"Already published and pushed for {d}: nothing to do."}
    else:
        nxt = {"type": "done", "pushed": False, "summary": f"Published. Commit published/x/editions/{d}.json and push."}
    st["next"] = nxt
    return st


def status_cmd(args) -> None:
    st = status(args.date, Path(args.published))
    if args.json:
        print(json.dumps(st, indent=2))
        return
    print(f"[x] {args.date}: scan {st['scan']}, prep {st['prep']}, edition {st['edition']}, published {st['published']}")
    for p in st.get("scan_problems", []) + st.get("edition_errors", []):
        print(f"  - {p}")
    print(f"[x] next: {st['next']}")


def today() -> str:
    """Today's date in Pacific time, where Wire dates everything, whatever the machine's own zone (a UTC server would roll
    over at 5 PM PT)."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def doctor_check() -> tuple[str, str]:
    """For `wire doctor`: the accounts file and the age of the newest scan. A warning, never a failure: a podcast-only
    machine has no X data."""
    try:
        rows = accounts()
    except ValueError as e:
        return "fail", str(e)
    n = len(rows)
    n_si = sum(a.get("lens") == "si" and a.get("tier") == "core" for a in rows)
    scans = sorted((x_dir() / "scan").glob("*/manifest.json")) if (x_dir() / "scan").is_dir() else []
    if not n:
        return "warn", f"no accounts in {ACCOUNTS}"
    if n_si > MAX_SI_ACCOUNTS:
        return "warn", f"{n_si} core SI accounts; the cap is {MAX_SI_ACCOUNTS} (scanner limits: xdaily.MAX_SI_ACCOUNTS)"
    if not scans:
        return "warn", f"{n} accounts; no scan yet in {x_dir() / 'scan'}"
    age = (datetime.now(timezone.utc).date() - date.fromisoformat(scans[-1].parent.name)).days
    return ("ok" if age <= 1 else "warn"), f"{n} accounts; newest scan {scans[-1].parent.name} ({age} days old)"
