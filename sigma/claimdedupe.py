"""Merge claims that restate one point. Deterministic, no model.

Where the repeats come from: a claim reaches an episode from independent passes (the ranking reader's claims, the daily
report's signal bullets, its section claims, and a weekly's claims for the same episode). Each pass words the same
moment its own way, so exact-text matching never caught them and a reader saw one point three times.

Two claims of one episode are the same point when all of these hold:
  - the same speaker (a role such as "guest", or "unknown", matches any name),
  - both carry a timestamp and the timestamps are at most WINDOW seconds apart,
  - and either they share their key numbers (the same ones, or one names some of the other's) and most of the shorter one's words,
    or their word overlap alone is high (Jaccard at least JACCARD, or JACCARD_SAME_MOMENT when within SAME_MOMENT seconds, or
    the shorter is almost contained in the longer).
Two claims never merge when their numbers conflict ("grew 45%" and "grew 147%"; 45% and 45; $5M and $5B), when one denies what
the other says or they use opposite words ("grew" and "fell", "raised" and "cut"), when their tags are different companies, or when
each names something the other does not ("Acme ... 10%" and "Beta ... 10%").
A group of repeats collapses into its most complete claim (the one with the most words, the ranking reader's on a tie);
tags are the union of the group's, and any score or rating the keeper lacks comes from the group.
"""
from __future__ import annotations

import copy
import re

WINDOW = 60          # seconds between two mentions of one point
SHARED_NUMBERS = 0.5  # share of the shorter claim's words the longer must contain when both name the same figures
SHARED_SOME_NUMBERS = 0.7  # ... when one names only some of the other's figures
JACCARD = 0.5
SAME_MOMENT = 15      # seconds: this close, a lower word overlap is still one point
JACCARD_SAME_MOMENT = 0.4
CONTAINED = 0.8       # of the shorter claim's words, with at least MIN_WORDS of them
MIN_WORDS = 5
SHARED_FIGURES = 3    # this many identical figures make one data statement: an opposite word ('fell ... gained share') or one extra name ('Chinese') is no conflict
ROLES = {"", "unknown", "guest", "host", "interviewer", "speaker", "narrator"}
STOP = frozenset("""a an and are as at be been being but by can could did do does for from had has have he her his how i if in into is it
its not of on or our out over said say says she so than that the their them then there these they this those to up was we were what when
which who will with would you your about also just very more most much some any each both than too still yet""".split())

_NUM = re.compile(r"(?<![A-Za-z\d.])(\d[\d,]*(?:\.\d+)?)(?:(%|\s?percent\b)|(?:\s?(thousand|million|billion|trillion)\b|(k|mn|bn|m|b|t)\b))?", re.I)
_SCALE = {"thousand": "k", "million": "m", "mn": "m", "billion": "b", "bn": "b", "trillion": "t", "k": "k", "m": "m", "b": "b", "t": "t"}
NEGATION = frozenset("not no never without cannot nor neither none".split())
OPPOSITES = [(frozenset(p.split()), frozenset(q.split())) for p, q in (
    ("""raise raised raises raising increase increased increases grew grow grows growing rose rise rises up higher accelerate accelerates
        accelerated positive expand expands expanded beat beats surge surged double doubled doubles""",
     """cut cuts cutting lower lowered lowers reduce reduced reduces decrease decreased decreases fell fall falls falling drop dropped drops
        down decelerate decelerates decelerated negative shrink shrinks shrank miss missed misses plunge plunged slow slowed slows halve
        halved halves"""),
    ("over exceeds exceeded exceed", "under"), ("more", "less fewer"),
    ("buy buys buying overweight long", "sell sells selling underweight short"),
    ("bought acquired", "sold divested"),
    ("gain gains gained", "lose loses lost loss"),
    ("overvalued expensive", "undervalued cheap"),
    ("increasingly", "decreasingly"),
    ("before", "after"), ("earlier", "later"), ("above", "below"), ("faster", "slower"), ("accelerating", "decelerating"),
    ("approve approved approves", "reject rejected rejects deny denied"), ("win won wins", "lose lost loses"),
    ("month monthly", "year yearly annual annually"),
)]
GENERIC = frozenset("ai gpu gpus llm llms api apis ceo cfo cto cpu cpus us uk eu ipo ml".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9.']*")


def _norm_text(text: str) -> str:
    return re.sub(r"\b([A-Za-z])-(\d)", r"\1\2", text or "")  # "S-1" is a name, not the number 1


def numbers(text: str) -> frozenset[str]:
    return frozenset(_figures(text))


def _figures(text: str) -> dict[str, set[str | None]]:
    """figure -> its scales: "$5B" and "5 billion" are ("5", {"b"}); 45% is "45%", a different figure from 45."""
    out: dict[str, set] = {}
    for m, pct, word, abbr in _NUM.findall(_norm_text(text)):
        m = m.replace(",", "").rstrip(".")
        key = (m[:-2] if m.endswith(".0") else m) + ("%" if pct else "")
        out.setdefault(key, set()).add(_SCALE.get((word or abbr).lower()))
    return out


def scale_conflict(xa: str, xb: str) -> bool:
    """The same figure with two different scales: $5 billion revenue / $2 million profit against the reverse. A figure with no scale
    ("$800 to $900 billion") matches either."""
    fa, fb = _figures(xa), _figures(xb)
    return any((sa := fa[k] - {None}) and (sb := fb[k] - {None}) and sa != sb for k in fa.keys() & fb.keys())


def opposite_words(xa: str, xb: str) -> bool:
    """grew / fell, over / under, bought / sold: one side's word in one claim, the other side's in the other, and neither claim uses
    both. The pairs are matched word for word ("sold" against "buy" is no pair), so a plain "sold to" never blocks a merge."""
    wa, wb = {t.lower() for t in _tokens(xa)}, {t.lower() for t in _tokens(xb)}
    return any(x & p and y & q and not x & q and not y & p for p, q in OPPOSITES for x, y in ((wa, wb), (wb, wa)))


def _tokens(text: str) -> list[str]:
    return [t.strip(".,;:!?()\"") for t in _norm_text(text).replace("\u2019", "'").split()]


def _negation_scope(text: str) -> frozenset[str]:
    """The first content words after the first negation word, or nothing when the text is not negated."""
    toks = _tokens(text)
    for i, w in enumerate(toks):
        if w.lower() in NEGATION or w.lower().endswith("n't"):
            after = [w for w in toks[i + 1:i + 6] if words(w)]  # in sentence order: a set would pick different words per run
            return frozenset(words(" ".join(after[:3]))) or frozenset({"?"})
    return frozenset()


def opposite(xa: str, xb: str) -> bool:
    """One says what the other denies: "will license X" against "will not license X". A shorter claim that merely leaves out a
    "not yet in the income statement" clause is not the opposite."""
    sa, sb = _negation_scope(xa), _negation_scope(xb)
    if sa and sb:  # both deny something: the same thing, or two different claims
        return not (sa <= words(xb) or sb <= words(xa))
    return bool((sa and sa <= words(xb)) or (sb and sb <= words(xa)))


def _name(t: str) -> str | None:
    t = re.sub(r"'s$", "", t)
    return t.lower() if re.fullmatch(r"[A-Z][A-Za-z0-9&]+", t) and t.lower() not in STOP else None


def names(text: str) -> frozenset[str]:
    """Capitalised words other than the generic ones ("AI", "CEO"): the things a claim is about."""
    return frozenset(n for t in _tokens(text) if (n := _name(t)) and n not in GENERIC)


def about_different_things(xa: str, xb: str) -> bool:
    """Each names something the other does not mention ("Acme revenue ..." against "Beta revenue ..."; "sold to Acme" against "sold to
    Beta"). A capitalised word the other claim also uses, in any case ("Future" against "future"), is no difference, and the first word
    of a sentence, often a plain one, counts only when the claims share no name at all."""
    low = lambda x: {t.lower().replace("'s", "") for t in _tokens(x)}  # noqa: E731
    la, lb = low(xa), low(xb)
    na, nb = names(xa), names(xb)
    if not na & nb and any(n not in lb for n in na) and any(n not in la for n in nb):
        return True
    ma, mb = (names(" ".join(_tokens(x)[1:])) for x in (xa, xb))  # inside the sentence
    return bool(any(n not in lb for n in ma) and any(n not in la for n in mb))


def words(text: str) -> frozenset[str]:
    """Content words, lowercased, plural -s dropped; numbers count as words."""
    out = set()
    for w in _WORD.findall(_norm_text(text).lower().replace(",", "")):
        w = w.strip(".'")
        if not w or w in STOP:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return frozenset(out)


def same_speaker(a, b) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return a == b or a in ROLES or b in ROLES


def different_tags(a: dict, b: dict) -> bool:
    ta, tb = ({str(t).lower().removeprefix("private:") for t in (c.get("tickers") or [])} for c in (a, b))
    return bool(ta and tb and not ta & tb)


def same_point(a: dict, b: dict) -> bool:
    ta, tb = a.get("timestamp"), b.get("timestamp")
    if not (isinstance(ta, int | float) and isinstance(tb, int | float)) or abs(ta - tb) > WINDOW:
        return False
    if not same_speaker(a.get("speaker"), b.get("speaker")):
        return False
    xa, xb = a.get("text") or "", b.get("text") or ""
    na, nb = numbers(xa), numbers(xb)
    if na and nb and not (na <= nb or nb <= na):
        return False  # different figures: different facts
    if scale_conflict(xa, xb) or opposite(xa, xb) or opposite_words(xa, xb) or (about_different_things(xa, xb) and len(na & nb) < SHARED_FIGURES) or different_tags(a, b):
        return False
    wa, wb = words(xa), words(xb)
    if not wa or not wb:
        return False
    common = len(wa & wb)
    small = min(len(wa), len(wb))
    if na and nb and common / small >= (SHARED_NUMBERS if na == nb else SHARED_SOME_NUMBERS):
        return True
    jac = common / len(wa | wb)
    if jac >= JACCARD or (abs(ta - tb) <= SAME_MOMENT and jac >= JACCARD_SAME_MOMENT):
        return True
    return (small >= MIN_WORDS and common / small >= CONTAINED)


def restated_pairs(claims: list[dict]) -> list[tuple[dict, dict]]:
    """Every pair of claims of one episode that make the same point (same_point), by comparing all pairs. The data-quality check
    over published claims: after `dedupe` it finds none, because a claim that matched a kept one was dropped."""
    return [(a, b) for i, a in enumerate(claims) for b in claims[i + 1:]
            if a.get("episode_id") == b.get("episode_id") and same_point(a, b)]


def _completeness(c: dict) -> tuple:
    t = c.get("timestamp")
    return (len(words(c.get("text") or "")), c.get("source") == "ranked", -(t if isinstance(t, int | float) else 0))


def _dedupe_once(claims: list[dict]) -> tuple[list[dict], list[tuple[dict, list[dict]]]]:
    """(claims without the repeats, in their first-seen order; [(kept, dropped...)] for every group that merged).
    Claims are dicts with episode_id, speaker, timestamp, text, and optionally tickers, novelty, verifiable, score, source.
    Kept claims are copies; nothing passed in is changed. Every dropped claim matches the claim kept in its place, never
    only another repeat, so a chain of near-matches cannot walk one point into a different one."""
    order = sorted(range(len(claims)), key=lambda i: _completeness(claims[i]), reverse=True)  # stable: ties keep input order
    groups: list[list[int]] = []  # the first index of each is its keeper
    named: list[set[str]] = []  # the named speakers in each group: a role such as "host" must not join two different people
    for i in order:
        who = (claims[i].get("speaker") or "").strip().lower()
        who = who if who not in ROLES else None
        for g, n in zip(groups, named):
            if claims[g[0]].get("episode_id") == claims[i].get("episode_id") and same_point(claims[g[0]], claims[i]) \
                    and not (who and n and who not in n):
                g.append(i)
                n.update([who] if who else [])
                break
        else:
            groups.append([i])
            named.append({who} if who else set())
    first = {min(g): g for g in groups}  # a group sits where its earliest member was
    out, merged = [], []
    for i in sorted(first):
        g = first[i]
        if len(g) == 1:
            out.append(copy.deepcopy(claims[g[0]]))
            continue
        members = [claims[k] for k in g]
        best = members[0]
        keep = copy.deepcopy(best)
        tags = list(dict.fromkeys(t for m in members for t in (m.get("tickers") or [])))
        if "tickers" in keep or tags:
            keep["tickers"] = tags
        for k in ("novelty", "verifiable", "score"):
            if keep.get(k) is None:
                keep[k] = next((m[k] for m in members if m.get(k) is not None), None)
        if (keep.get("speaker") or "").strip().lower() in ROLES:
            keep["speaker"] = next((m["speaker"] for m in members if (m.get("speaker") or "").strip().lower() not in ROLES), keep.get("speaker"))
        if any(m.get("source") == "ranked" for m in members):
            keep["source"] = "ranked"  # library.stored_scores reuses a run's ranked claims: a merged one must stay among them
        out.append(keep)
        merged.append((keep, members[1:]))
    return out, merged


def dedupe(claims: list[dict]) -> tuple[list[dict], list[tuple[dict, list[dict]]]]:
    """_dedupe_once repeated until nothing merges. A merged claim takes the union of its members' tags, and a tag set can
    make it conflict or match differently than the keeper did, so one pass is not always a fixed point; this makes dedupe
    idempotent, which the export gate and a re-ingest rely on. Each pass drops at least one claim, so it ends."""
    out, merged = _dedupe_once(claims)
    while True:
        nxt, more = _dedupe_once(out)
        if not more:
            return out, merged
        out, merged = nxt, merged + more
