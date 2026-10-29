"""Per-ticker sentiment from the day's X signals: one deterministic step, no model, no network.

    aggregate(signals) -> [row, ...]      called by signals_index.build; written into published/signals/D.json as `tickers[]` and `markets[]`

The signals (signals_index.py) are single stances, -2..+2, from X posts. This module groups them by ticker and says what the day's X
voices add up to, so a reader sees "MU: Bullish, 3 speakers" or "AMZN: Mixed" rather than five separate lines. The rules, in the
order they are applied (every number is in this file; change one here only):

  1. One vote per speaker per ticker. A speaker's several posts on a ticker are one vote: the mean of their stances. A speaker's
     weight is that of their best-weighted post: primary 1.0, recap 0.5 (a recap relays news or someone else's view).
  2. net = sum(weight x vote) / sum(weight), on the stance scale -2..+2.
  3. bull, bear, neutral count speakers: a vote above 0, below 0, or a speaker whose label for the ticker is 0 (a mention with no
     call) or whose own posts cancel out. Neutral voters are counted but carry no weight in `net`: "no call" is not evidence.
  4. Mixed: bull weight and bear weight are the summed weights of the two sides. The minority side is the lighter one. The ticker
     is Mixed when the minority weight is at least MIX_MIN_WEIGHT (one primary voter, or two recaps, or one recap besides
     anything) and at least MIX_MIN_SHARE of the two sides' total. 3 primary bulls against 1 primary bear is Mixed (25%); 4 against 1
     is not (20%); 1 primary against 1 recap is Mixed (33%).
  5. Otherwise the label is the 5-step scale on net: >= 1.5 Strongly bullish, >= 0.5 Bullish, > -0.5 Neutral, > -1.5 Bearish, else Strongly bearish.
  6. agreement = |bull weight - bear weight| / (bull weight + bear weight), 1 when every voter is on one side; dispersion = the weighted
     standard deviation of the votes around net, in stance units.
  7. confidence: high with 3 or more voting speakers and at least half of them primary; low with one speaker or no primary voter;
     else medium. A Mixed label has a confidence too: how sure we are that the voices really split.
  8. rank = speakers x |net|, and speakers x dispersion for a Mixed ticker (its net is near 0 by definition, so |net| would bury it).
     The ticker tape lists tickers by rank and always keeps Mixed ones in.

  9. reason: what was said, in two lines at most, never the counts (the tally and label are shown once, next to the ticker). One side:
     the best one or two distinct claims, e.g. "Sold-out supply through 2029 · Strong pricing in its Q3 call". Both sides (Mixed, or a
     lean with a dissenter): "▲ <best bullish claim> · ▼ <best bearish claim>". A claim is the signal's own reason, with a leading
     "Says / Reports / Calls" dropped and cut at its first clause when longer than CLAIM_WORDS; a second claim is added only when it shares
     less than 40% of its content words with the first. The labeller writes every reason in its own words (the 12-word quote rule).

Standard library only: the site host builds with nothing else.
"""
from __future__ import annotations

import re
from collections import defaultdict

ORIGIN_WEIGHT = {"primary": 1.0, "recap": 0.5}
MIX_MIN_WEIGHT = 0.5
MIX_MIN_SHARE = 0.25
STRONG, LEAN = 1.5, 0.5
LABELS = ("Strongly bearish", "Bearish", "Neutral", "Bullish", "Strongly bullish", "Mixed")
SYMBOL = {"Strongly bearish": "▼", "Bearish": "▼", "Neutral": "●", "Bullish": "▲", "Strongly bullish": "▲", "Mixed": "◆"}
CLASS = {"Strongly bearish": "neg", "Bearish": "neg", "Neutral": "neu", "Bullish": "pos", "Strongly bullish": "pos", "Mixed": "mix"}
CONFIDENCE = ("low", "medium", "high")
CLAIM_WORDS = 10  # a claim longer than this is cut at its first clause
ONE_SIDE_WORDS = 24  # most words in a one-sided summary (two claims)
_LEAD = re.compile(r"^(?:says|reports|relays)\s+(?:that\s+)?", re.I)
_NOCALL = re.compile(r"[;,]\s+(?:but\s+)?no (?:explicit |clear |stated )?(?:call|view|position|trade)\b.*$", re.I)
_CUT = re.compile(r"\s*[;,]\s+|\s+(?:but|though|while)\s+", re.I)
_STOP = frozenset("a an the of to in on at for and or but is are was were be it its that this with as by from than more not no".split())


def badge(r: dict) -> str:
    """'▲ Bullish', '◆ Mixed', '▼▼ Bearish' (the arrow is doubled for a strong view): how every page writes a row's label."""
    lab = r["label"]
    return f"{SYMBOL[lab]}{SYMBOL[lab] if lab.startswith('Strongly') else ''} {lab.split()[-1].capitalize()}"


def tally(r: dict) -> str:
    """'3/3' (3 of the 3 speakers with a view are bullish; '2/3 ' on a bearish lean means 2 of 3 are bearish) or, for a split, 'bull/bear': '1/1'."""
    if r["label"] == "Mixed" or not (r["bull"] and r["bear"]) and not r["speakers"]:
        return f"{r['bull']}/{r['bear']}"
    lead = r["bull"] if r["net"] > 0 else r["bear"] if r["net"] < 0 else None
    return f"{lead}/{r['speakers']}" if lead is not None else f"{r['bull']}/{r['bear']}"


TALLY_NOTE = "The tally is the speakers on the leading side out of those with a view; for a split (Mixed) it is bullish/bearish."


def head(r: dict) -> str:
    """The one line that carries the label and the tally: '▲ Bullish · 3/3'. Said once; no page repeats it."""
    return f"{badge(r)} · {tally(r)}"


def label_for(net: float) -> str:
    if net >= STRONG:
        return "Strongly bullish"
    if net >= LEAN:
        return "Bullish"
    if net > -LEAN:
        return "Neutral"
    return "Bearish" if net > -STRONG else "Strongly bearish"


def _votes(sigs: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for s in sigs:
        by[s["speaker"]].append(s)
    out = []
    for who, ss in sorted(by.items()):
        out.append({"speaker": who, "vote": sum(s["stance"] for s in ss) / len(ss), "weight": max(ORIGIN_WEIGHT.get(s["origin"], 0.5) for s in ss),
                    "primary": any(s["origin"] == "primary" for s in ss), "signals": ss})
    return out


def _words(text: str) -> set:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9$%.]+", text.lower().replace("-", " ")) if w not in _STOP}


def _claim(reason: str) -> str:
    """The signal's reason as a short claim: lead verb dropped, cut at the first clause if long, sentence case, no final stop."""
    t = _NOCALL.sub("", _LEAD.sub("", reason.strip())).rstrip(". ")
    if len(t.split()) > CLAIM_WORDS:
        for piece in _CUT.split(t):
            if len(piece.split()) >= 4:
                t = piece
                break
    return t[:1].upper() + t[1:]


def _side(votes: list[dict], sign: int, limit: int) -> str:
    """Up to `limit` distinct claims from one side's signals, strongest first, joined with ' · '."""
    sigs = sorted((s for v in votes if v["vote"] * sign > 0 for s in v["signals"] if s["stance"] * sign > 0),
                  key=lambda s: (-ORIGIN_WEIGHT.get(s["origin"], 0.5) * abs(s["stance"]), s["origin"] != "primary", s["id"]))
    out: list[str] = []
    for s in sigs:
        c = _claim(s["reason"])
        if any(len(_words(c) & _words(o)) >= 0.4 * min(len(_words(c)), len(_words(o))) for o in out):
            continue
        if out and sum(len(o.split()) for o in out) + len(c.split()) > ONE_SIDE_WORDS:
            break
        out.append(c)
        if len(out) == limit:
            break
    return " · ".join(out)


def _reason(label: str, votes: list[dict], bull: int, bear: int, net: float) -> str:
    """What was said (rule 9): no counts, no label."""
    if bull and bear:
        return f"▲ {_side(votes, 1, 1)} · ▼ {_side(votes, -1, 1)}"
    sign = 1 if bull else -1 if bear else 0
    return _side(votes, sign, 2) if sign else ""


def row(ticker: str, target: str, sigs: list[dict], neutral: int = 0) -> dict:
    """The aggregate of one ticker's signals. `neutral` is how many more speakers mentioned it with no call."""
    votes = _votes(sigs)
    voting = [v for v in votes if v["vote"]]
    bull_w = sum(v["weight"] for v in voting if v["vote"] > 0)
    bear_w = sum(v["weight"] for v in voting if v["vote"] < 0)
    total_w = bull_w + bear_w
    net = sum(v["weight"] * v["vote"] for v in voting) / total_w if total_w else 0.0
    bull, bear = sum(v["vote"] > 0 for v in voting), sum(v["vote"] < 0 for v in voting)
    flat = neutral + len(votes) - len(voting)
    minority = min(bull_w, bear_w)
    mixed = minority >= MIX_MIN_WEIGHT and minority / total_w >= MIX_MIN_SHARE if total_w else False
    label = "Mixed" if mixed else label_for(net)
    disp = (sum(v["weight"] * (v["vote"] - net) ** 2 for v in voting) / total_w) ** 0.5 if total_w else 0.0
    primary_share = sum(v["primary"] for v in voting) / len(voting) if voting else 0.0
    conf = "high" if len(voting) >= 3 and primary_share >= 0.5 else "low" if len(voting) < 2 or primary_share == 0 else "medium"
    rank = len(voting) * (disp if mixed else abs(net))
    return {"ticker": ticker, "target": sigs[0].get("target") or ticker, "label": label, "net": round(net, 2), "speakers": len(voting),
            "bull": bull, "bear": bear, "neutral": flat, "primary_share": round(primary_share, 2),
            "agreement": round(abs(bull_w - bear_w) / total_w, 2) if total_w else 0.0, "dispersion": round(disp, 2),
            "confidence": conf, "rank": round(rank, 2), "reason": _reason(label, votes, bull, bear, net),
            "signal_ids": sorted(s["id"] for s in sigs)}


def aggregate(signals: list[dict], neutral: dict[str, int] | None = None, market: bool = False) -> list[dict]:
    """Rows for the X signals of `signals`, tickers only (market=False) or only the @ market targets (market=True), best rank first.
    A ticker with only neutral mentions has no row: there is no signal to aggregate."""
    g = defaultdict(list)
    for s in signals:
        if s.get("source_kind") == "x" and str(s["ticker"]).startswith("@") == market:
            g[s["ticker"]].append(s)
    rows = [row(t, ss[0].get("target") or t, ss, (neutral or {}).get(t, 0)) for t, ss in g.items()]
    return sorted(rows, key=lambda r: (-r["rank"], -r["speakers"], r["ticker"]))


def tape_rows(rows: list[dict], n: int = 12, mixed_extra: int = 4) -> list[dict]:
    """The rows the ticker tape scrolls: the best `n` by rank that lean one way or are Mixed, then any further Mixed ones (up to
    `mixed_extra`) so a split ticker is never cut, all in rank order."""
    live = [r for r in rows if r["label"] != "Neutral"]
    top = live[:n]
    extra = [r for r in live[n:] if r["label"] == "Mixed"][:mixed_extra]
    return sorted(top + extra, key=lambda r: (-r["rank"], -r["speakers"], r["ticker"]))
