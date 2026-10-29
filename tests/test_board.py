"""The ticker board: the score formula and the check on what a reader may label."""
import json
from datetime import date

import pytest

from sigma import board, stance, tickers

US = {"AAA": "Signals Inc", "BBB": "Beta Inc"}
TODAY = date(2026, 10, 26)


def rec(ticker, st, kind, quality, d, source):
    return {"ticker": ticker, "stance": st, "reason": "r", "kind": kind, "quality": quality, "date": d, "sources": [source],
            "who": "w", "where": "s", "link": ""}


def test_score_follows_the_owners_formula_worked_by_hand():
    """outside-value: score = strength x kind weight x quality x 0.5^(age/30), items up to 90 days old (owner's design,
    2026-10-26; half-life 30 days, YouTube weight 1, mild views count a quarter and nothing on X, all 2026-10-27).
    Strength: +-2 counts 2; +-1 counts 2 x .25 = .5 for deep and YouTube, 0 for X. By hand: deep +2, quality .8, 30 days
    old = 2 x 1 x .8 x .5 = .8; YouTube -1, quality 1, today = -.5 x 1 = -.5; X +2, quality .6, 60 days old =
    2 x .5 x .6 x .25 = .15; X +1 today = 0. A neutral or mild-X mention adds to the count only; an item 91 days old is
    left out."""
    rows = board.score([
        rec("AAA", 2, "deep", 0.8, "2026-09-26", "ep1"), rec("AAA", -1, "social", 1.0, "2026-10-26", "ep2"),
        rec("AAA", 2, "x", 0.6, "2026-08-27", "bob"), rec("AAA", 0, "deep", 0.8, "2026-10-26", "ep1"),
        rec("AAA", 1, "x", 0.6, "2026-10-26", "carl"),
        rec("AAA", 2, "x", 0.6, "2026-07-27", "old"),
        rec("BBB", 0, "deep", 0.8, "2026-10-26", "ep3"),  # only a mention: no row
    ], TODAY, US)["rows"]
    assert [r["ticker"] for r in rows] == ["AAA"]
    a = rows[0]
    assert (round(a["net"], 3), round(a["bull"], 3), round(a["bear"], 3)) == (0.45, 0.95, 0.5)
    assert (a["mentions"], a["sources"], a["last"]) == (5, 4, "2026-10-26")


def test_merge_refuses_non_us_tickers_and_unlabelled_candidates_and_writes_nothing(tmp_path, monkeypatch):
    """stated-rule (the owner's design): only valid US tickers count, and every candidate of a claim gets a label."""
    monkeypatch.setattr(tickers, "load", lambda path=None: US)
    pub, run = tmp_path / "published", tmp_path / "runs" / "r1"
    (pub / "r1").mkdir(parents=True)
    claim = {"episode_id": "e1", "timestamp": 5, "text": "Calls AAA a long and BBB neutral", "date": "2026-10-25",
             "tickers": ["AAA", "BBB", "private:Acme", "005930.KS"]}
    (pub / "r1" / "claims.jsonl").write_text(json.dumps(claim) + "\n")
    assert stance.prep(str(run), None, pub)["to_label"] == 1  # the private name and the Korean line are never candidates
    key = json.loads((run / "stance" / "in-1.json").read_text())[0]["key"]
    lab = lambda tk, st=2: {"ticker": tk, "stance": st, "reason": "calls it a long"}
    (run / "stance" / "out-1.json").write_text(json.dumps([{"key": key, "labels": [lab("AAA"), lab("005930.KS")]}]))
    with pytest.raises(stance.StanceError) as e:
        stance.merge(str(run), None, pub)
    assert "005930.KS is not a US-listed ticker" in str(e.value) and "no label for BBB" in str(e.value)
    assert not (pub / "r1" / "stances.jsonl").exists()
    (run / "stance" / "out-1.json").write_text(json.dumps([{"key": key, "labels": [lab("AAA"), lab("BBB", 0)]}]))
    assert stance.merge(str(run), None, pub)["added"] == 1
    assert [x["ticker"] for x in json.loads((pub / "r1" / "stances.jsonl").read_text())["labels"]] == ["AAA", "BBB"]


def test_market_lines_follow_the_same_formula_and_count_broad_funds_once():
    """outside-value, by hand with the formula above and the rule that a broad index fund also speaks
    for Market, once per item. All dated today, so no decay. Market: @MARKET deep +2, quality .8 = 1.6; SPY YouTube +1,
    quality 1 = .5 (mild; no Market label of its own, so it counts); an item with @MARKET YouTube -1 = -.5 and SPY deep +2 (the
    fund adds nothing, the item already speaks for Market); IWM +2 with QQQ -2 is a bet between funds (nothing); a sector
    fund XLK +2 (nothing). Net 1.6 + .5 - .5 = 1.6, bull 2.1, bear .5, three items. Rates has none."""
    us = {"SPY": "S&P fund", "IWM": "R2000 fund", "QQQ": "Nasdaq fund", "XLK": "Tech fund"}
    keyed = lambda key, *a: {**rec(*a), "key": key}
    sc = board.score([
        keyed("k1", "@MARKET", 2, "deep", 0.8, "2026-10-26", "e1"),
        keyed("k2", "SPY", 1, "social", 1.0, "2026-10-26", "e2"),
        keyed("k3", "@MARKET", -1, "social", 1.0, "2026-10-26", "e3"), keyed("k3", "SPY", 2, "deep", 1.0, "2026-10-26", "e3"),
        keyed("k4", "IWM", 2, "deep", 1.0, "2026-10-26", "e4"), keyed("k4", "QQQ", -2, "deep", 1.0, "2026-10-26", "e4"),
        keyed("k5", "XLK", 2, "deep", 1.0, "2026-10-26", "e5"),
    ], TODAY, us)
    assert [m["label"] for m in sc["market"]] == ["Market", "Rates", "Credit"]
    m = sc["market"][0]
    assert (round(m["net"], 3), round(m["bull"], 3), round(m["bear"], 3), m["mentions"]) == (1.6, 2.1, 0.5, 3)
    assert sc["market"][1]["items"] == [] and sc["market"][2]["items"] == []
    assert {r["ticker"] for r in sc["rows"]} == set(us)  # the funds keep their own rows; no market line among the tickers


def test_market_labels_are_added_to_labelled_items_without_touching_their_ticker_labels(tmp_path, monkeypatch):
    """stated-rule: an item labelled before market targets existed is offered again for market labels
    only; its stored ticker label is never rewritten, labelled() joins both rows without duplicates, and a second prep
    offers nothing. A claim that names no ticker but reads like a market view is offered too; declining it is a row."""
    monkeypatch.setattr(tickers, "load", lambda path=None: US)
    pub, run = tmp_path / "published", tmp_path / "runs" / "r1"
    (pub / "r1").mkdir(parents=True)
    a = {"episode_id": "e1", "timestamp": 1, "text": "Calls AAA a long, and expects the Fed to cut rates", "date": "2026-10-25", "tickers": ["AAA"]}
    b = {"episode_id": "e1", "timestamp": 2, "text": "The Fed will cut rates twice", "date": "2026-10-25", "tickers": []}
    c = {"episode_id": "e1", "timestamp": 3, "text": "Widgets ship in March", "date": "2026-10-25", "tickers": []}
    (pub / "r1" / "claims.jsonl").write_text("".join(json.dumps(x) + "\n" for x in (a, b, c)))
    ka, kb = stance.claim_key("e1", 1, a["text"]), stance.claim_key("e1", 2, b["text"])
    old_row = json.dumps({"key": ka, "labels": [{"ticker": "AAA", "stance": 2, "reason": "calls it a long"}]}) + "\n"
    (pub / "r1" / "stances.jsonl").write_text(old_row)
    r = stance.prep(str(run), None, pub)
    assert (r["to_label"], r["market_only"]) == (1, 1)  # b is new, a is owed a market read, c is neither
    rates = {"ticker": "@RATES", "stance": 1, "reason": "expects the Fed to cut rates"}
    out = run / "stance" / "out-1.json"
    out.write_text(json.dumps([{"key": ka, "labels": [{"ticker": "AAA", "stance": -2, "reason": "flipped it"}]}, {"key": kb, "labels": []}]))
    with pytest.raises(stance.StanceError):  # a market-only item cannot change its ticker label
        stance.merge(str(run), None, pub)
    assert (pub / "r1" / "stances.jsonl").read_text() == old_row
    out.write_text(json.dumps([{"key": ka, "labels": [rates]}, {"key": kb, "labels": []}]))
    assert stance.merge(str(run), None, pub)["added"] == 2
    lines = (pub / "r1" / "stances.jsonl").read_text().splitlines(keepends=True)
    assert lines[0] == old_row and len(lines) == 3
    assert [x["ticker"] for x in stance.labelled(pub)[ka]] == ["AAA", "@RATES"]
    assert stance.labelled(pub)[kb] == []
    assert stance.prep(str(run), None, pub)["batches"] == 0


def test_x_posts_are_labelled_themselves_and_the_sentence_summing_them_up_counts_only_on_days_without_post_labels(tmp_path, monkeypatch):
    """stated-rule: X is labelled post by post, a retweet or a bare link is no candidate, an author's
    self-reply thread is one item (one view, not one per post), and a post and the edition sentence that sums it up never count twice. A day with only sentence labels keeps counting its sentences.
    By hand: 03:10 UTC on Oct 27 is 20:10 PDT on Oct 26, so the post's day is the 26th."""
    monkeypatch.setattr(tickers, "load", lambda path=None: US)
    monkeypatch.setenv("SIGMA_X_DIR", str(tmp_path / "x"))
    scan = tmp_path / "x" / "scan" / "2026-10-26"
    scan.mkdir(parents=True)
    post = lambda i, text, **kw: {"id": i, "handle": "alice", "created_at": "2026-10-27T03:10:00Z", "text": text, "cashtags": [], "metrics": {}, **kw}
    posts = [post("11111", "Calls $AAA a buy after the report, margins look strong", cashtags=["$AAA"]),
             post("22222", "Stocks look set for a sell-off into the Fed meeting"),
             post("33333", "RT @bob: $AAA is great", is_repost=True), post("44444", "https://t.co/abc $AAA", cashtags=["$AAA"]),
             post("55555", "Lunch was great today, nothing else to say"),
             post("66666", "Thread on $BBB: demand looks strong this year", cashtags=["$BBB"]),  # a self-reply thread: one item, not two
             post("77777", "Second point on $BBB, margins should recover next year", cashtags=["$BBB"], in_reply_to_id="66666", in_reply_to_handle="alice"),
             post("88881", "Root of an older thread on $AAA, demand looks strong", cashtags=["$AAA"]),  # both posts were labelled one by one
             post("88882", "Second post of it, $AAA margins keep improving", cashtags=["$AAA"], in_reply_to_id="88881", in_reply_to_handle="alice")]
    (scan / "posts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in posts))
    pub = tmp_path / "published"
    (pub / "x" / "stances").mkdir(parents=True)
    (pub / "x" / "editions").mkdir()
    for day, handle, pid, text, tk in (("2026-10-26", "alice", "11111", "AAA looks strong", "AAA"), ("2026-10-25", "carol", "99999", "BBB looks strong", "BBB")):
        (pub / "x" / "editions" / f"{day}.json").write_text(json.dumps({"date": day, "signals": [{"text": text, "cites": [pid]}],
                                                                         "posts": [{"id": pid, "handle": handle, "lens": "signals", "date": day, "cashtags": []}]}))
        (pub / "x" / "stances" / f"{day}.jsonl").write_text(json.dumps({"key": stance.x_key(day, "signals", 0, text), "labels": [
            {"ticker": tk, "stance": 1, "reason": "sentence label"}]}) + "\n")
    with (pub / "x" / "stances" / "2026-10-26.jsonl").open("a") as fh:  # labelled before threads were one item: each post once
        for i in ("88881", "88882"):
            fh.write(json.dumps({"key": "p-" + i, "labels": [{"ticker": "AAA", "stance": 1, "reason": "own words"}], "market": True,
                                 "id": i, "handle": "alice", "date": "2026-10-26"}) + "\n")
    assert stance.prep(None, "2026-10-26", pub)["to_label"] == 3  # the buy call, the market view, the thread; not the repost, bare link or chatter
    items = json.loads((tmp_path / "x" / "days" / "2026-10-26" / "stance" / "in-1.json").read_text())
    thread = [i for i in items if i["key"] in ("p-66666", "p-77777")]  # keyed by its first post, both posts' words in order
    assert [(i["key"], i["id"], i["text"]) for i in thread] == [("p-66666", "66666", "Thread on $BBB: demand looks strong this year\n\nSecond point on $BBB, margins should recover next year")]
    lab = lambda t, s: {"ticker": t, "stance": s, "reason": "own words"}
    (tmp_path / "x" / "days" / "2026-10-26" / "stance" / "out-1.json").write_text(json.dumps([
        {"key": "p-11111", "labels": [lab("AAA", 2)]}, {"key": "p-22222", "labels": [lab("@MARKET", -1)]}]))
    assert stance.merge(None, "2026-10-26", pub)["added"] == 2
    recs = board.collect(pub, {}, US, stance.labelled(pub))
    got = sorted((r["ticker"], r["stance"], r["who"], r["link"], r["date"], r["kind"], r["quality"]) for r in recs)
    # the older thread counts once, as its first post: a thread is one view even in published data
    assert got == [("@MARKET", -1, "@alice", "https://x.com/alice/status/22222", "2026-10-26", "x", 0.6),
                   ("AAA", 1, "@alice", "https://x.com/alice/status/88881", "2026-10-26", "x", 0.6),
                   ("AAA", 2, "@alice", "https://x.com/alice/status/11111", "2026-10-26", "x", 0.6),
                   ("BBB", 1, "@carol", "https://x.com/carol/status/99999", "2026-10-25", "x", 0.6)]
