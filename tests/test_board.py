"""The ticker board: the score formula and the check on what a reader may label."""
import json
from datetime import date

import pytest

from sigma import board, stance, tickers

US = {"AAA": "Signals Inc", "BBB": "Beta Inc"}
TODAY = date(2026, 10, 26)


def rec(ticker, st, kind, quality, d, source):
    return {"ticker": ticker, "stance": st, "reason": "r", "kind": kind, "quality": quality, "date": d, "sources": [source],
            "who": source, "where": "s", "link": "", "origin": "primary"}


def test_each_speaker_gets_one_vote_and_mild_x_views_count():
    """Owner rule: one vote per speaker across video and X. By hand: (2-1+1)/3=.67; one bear is one third, so Mixed.
    Repeat claims and neutral mentions do not add voices or dilute a call; thirty-day-old items are outside the window."""
    rows = board.score([
        rec("AAA", 2, "deep", 0.8, "2026-10-25", "alice"), rec("AAA", 2, "deep", 0.8, "2026-10-26", "alice"),
        rec("AAA", -1, "social", 1.0, "2026-10-26", "bob"), rec("AAA", 0, "deep", 0.8, "2026-10-26", "alice"),
        rec("AAA", 1, "x", 0.6, "2026-10-26", "carl"), rec("AAA", 2, "x", 0.6, "2026-09-26", "old"),
        rec("BBB", 0, "deep", 0.8, "2026-10-26", "news"),
    ], TODAY, US)["rows"]
    assert [row["ticker"] for row in rows] == ["AAA"]
    row = rows[0]
    assert (row["label"], row["net"], row["bull"], row["bear"]) == ("Mixed", 0.67, 2, 1)
    assert (row["mentions"], row["sources"], row["last"]) == (5, 3, "2026-10-26")
    assert {item["speaker"] for item in row["items"]} == {"alice", "bob", "carl"}
    cancelled = board.score([
        rec("AAA", 2, "deep", 0.8, "2026-10-25", "alice"), rec("AAA", -2, "x", 0.6, "2026-10-26", "alice"),
        rec("AAA", 1, "x", 0.6, "2026-10-26", "bob"),
    ], TODAY, US)["rows"][0]
    assert (cancelled["label"], cancelled["bull"], cancelled["bear"], cancelled["neutral"]) == ("Bullish", 1, 0, 1)
    alice = next(item for item in cancelled["items"] if item["speaker"] == "alice")
    assert alice["vote"] == 0 and {source["stance"] for source in alice["evidence"]} == {-2, 2}


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


def test_market_uses_the_same_speaker_votes_and_counts_broad_funds_once():
    """By hand: direct Market +2, broad SPY +1 and direct Market -1 give .67 and two bulls/one bear.
    A source labeling Market adds no second vote through SPY. Long IWM/short QQQ is relative; XLK is sector-only."""
    us = {"SPY": "S&P fund", "IWM": "R2000 fund", "QQQ": "Nasdaq fund", "XLK": "Tech fund"}
    keyed = lambda key, *args: {**rec(*args), "key": key}
    scores = board.score([
        keyed("k1", "@MARKET", 2, "deep", 0.8, "2026-10-26", "e1"),
        keyed("k2", "SPY", 1, "social", 1.0, "2026-10-26", "e2"),
        keyed("k3", "@MARKET", -1, "social", 1.0, "2026-10-26", "e3"), keyed("k3", "SPY", 2, "deep", 1.0, "2026-10-26", "e3"),
        keyed("k4", "IWM", 2, "deep", 1.0, "2026-10-26", "e4"), keyed("k4", "QQQ", -2, "deep", 1.0, "2026-10-26", "e4"),
        keyed("k5", "XLK", 2, "deep", 1.0, "2026-10-26", "e5"),
    ], TODAY, us)
    assert len(scores["market"]) == 1
    market = scores["market"][0]
    assert (market["market_label"], market["label"], market["net"], market["bull"], market["bear"], market["sources"]) == ("Market", "Mixed", 0.67, 2, 1, 3)
    assert {row["ticker"] for row in scores["rows"]} == set(us)


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
