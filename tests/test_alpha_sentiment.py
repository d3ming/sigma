"""Per-ticker X sentiment (wire/alpha_sentiment.py): the rule, the day file's tickers[], the tape and the Sentiment page's X column."""
import json
import re


def sig(t, who, st, origin="primary", i=None, kind="x"):
    return {"id": i or f"a-{abs(hash((t, who, st, origin))) % 10**12:012x}", "ticker": t, "target": t, "speaker": who, "stance": st, "origin": origin,
            "source_kind": kind, "reason": f"{who} on {t}"}


def one(signals, neutral=None, t="AAA"):
    from wire import alpha_sentiment
    return next(r for r in alpha_sentiment.aggregate(signals, neutral) if r["ticker"] == t)


def test_the_label_follows_the_five_step_scale_and_a_clear_split_is_mixed():
    """stated-rule (alpha_sentiment.py docstring): thresholds on net, and Mixed when the lighter side weighs >= 0.5 and is >= 25% of both sides."""
    from wire import alpha_sentiment as a
    assert [a.label_for(n) for n in (2, 1.5, 1, 0.5, 0.4, 0, -0.4, -0.5, -1, -1.5, -2)] == [
        "Strongly bullish", "Strongly bullish", "Bullish", "Bullish", "Neutral", "Neutral", "Neutral", "Bearish", "Bearish", "Strongly bearish", "Strongly bearish"]
    assert one([sig("AAA", "@a", 2), sig("AAA", "@b", 1)])["label"] == "Strongly bullish"  # net 1.5
    assert one([sig("AAA", "@a", 1), sig("AAA", "@b", -1)])["label"] == "Mixed"  # 1 primary vs 1 primary
    three_one = [sig("AAA", w, 1) for w in "@a @b @c".split()] + [sig("AAA", "@d", -1)]
    assert one(three_one)["label"] == "Mixed"  # 25% on the lighter side is the line
    assert one(three_one + [sig("AAA", "@e", 1)])["label"] == "Bullish"  # 4 vs 1: 20%, a lean with one dissenter
    assert one([sig("AAA", "@a", 1), sig("AAA", "@b", -1, "recap")])["label"] == "Mixed"  # primary vs recap: 33%
    assert one([sig("AAA", "@a", 2), sig("AAA", "@b", -1, "recap")])["label"] == "Mixed"  # 0.5 / 1.5 = 33%
    assert one([sig("AAA", "@a", 1), sig("AAA", "@b", 1), sig("AAA", "@c", -1, "recap")])["label"] == "Bullish"  # 0.5 / 2.5 = 20%
    assert one([sig("AAA", "@a", -2)])["label"] == "Strongly bearish"


def test_one_vote_per_speaker_and_the_counts_confidence_and_rank():
    """stated-rule (alpha_sentiment.py rules 1, 3, 6, 7, 8): a speaker's posts are one vote; recaps weigh half; neutral mentions carry no weight."""
    r = one([sig("AAA", "@a", 2), sig("AAA", "@a", 1), sig("AAA", "@a", 2), sig("AAA", "@b", 1, "recap")], {"AAA": 2})
    assert (r["speakers"], r["bull"], r["bear"], r["neutral"]) == (2, 2, 0, 2)  # three posts by @a are one speaker
    assert r["net"] == round((1.0 * (5 / 3) + 0.5 * 1) / 1.5, 2) and r["label"] == "Bullish"  # 1.44, just under the strong line
    assert (r["primary_share"], r["agreement"], r["confidence"]) == (0.5, 1.0, "medium")
    assert abs(r["rank"] - 2 * abs(r["net"])) < 0.02 and r["signal_ids"] == sorted(r["signal_ids"]) and len(r["signal_ids"]) == 4
    assert one([sig("AAA", "@a", 1)])["confidence"] == "low"  # one speaker
    assert one([sig("AAA", "@a", 1, "recap"), sig("AAA", "@b", 1, "recap")])["confidence"] == "low"  # no first-hand voice
    assert one([sig("AAA", w, 1) for w in "@a @b @c".split()])["confidence"] == "high"
    # a speaker whose posts cancel out is a neutral voter, not a vote
    c = one([sig("AAA", "@a", 1), sig("AAA", "@a", -1), sig("AAA", "@b", 1)])
    assert (c["speakers"], c["neutral"], c["net"]) == (1, 1, 1.0)
    # mixed tickers rank by dispersion (their net is about 0), so they are not buried under a lone strong view
    from wire import alpha_sentiment as a
    rows = a.aggregate([sig("MIX", "@a", 2), sig("MIX", "@b", -2), sig("ONE", "@c", 1)])
    assert [x["ticker"] for x in rows] == ["MIX", "ONE"] and rows[0]["rank"] == 4.0


def test_only_x_signals_count_and_markets_are_kept_apart_and_the_tape_keeps_mixed_ones_in():
    """stated-rule (the tape lists per-ticker items by rank, Mixed always kept; podcast signals are not X; markets are not tickers)."""
    from wire import alpha_sentiment as a
    sigs = [sig("AAA", "@a", 1), sig("AAA", "Host", 2, kind="podcast"), sig("@MARKET", "@a", 1)]
    assert [r["ticker"] for r in a.aggregate(sigs)] == ["AAA"] and a.aggregate(sigs)[0]["speakers"] == 1
    assert [r["ticker"] for r in a.aggregate(sigs, market=True)] == ["@MARKET"]
    many = [sig(f"T{i:02d}", f"@s{i}{k}", 2) for i in range(14) for k in range(2)] + [sig("MIXA", "@x", 1), sig("MIXA", "@y", -1)]
    rows = a.aggregate(many)
    assert "MIXA" not in [r["ticker"] for r in rows[:12]]  # it ranks below the twelve strong ones
    tape = a.tape_rows(rows)
    assert len(tape) == 13 and "MIXA" in [r["ticker"] for r in tape]  # but it stays on the tape
    assert [r["rank"] for r in tape] == sorted((r["rank"] for r in tape), reverse=True)
    assert a.tape_rows([r for r in rows if r["label"] == "Mixed"] + [{**rows[0], "label": "Neutral"}]) == [r for r in rows if r["label"] == "Mixed"]


def test_the_built_day_file_carries_tickers_counts_neutral_speakers_and_validates(tmp_path):
    """stated-rule (schema/alpha-index.schema.json): tickers[] is in the day file and valid; neutral counts come from the stance-0 labels."""
    from wire import alpha_index
    pub = tmp_path / "alpha"
    pub.mkdir()
    signal = sig("AAA", "@a", 1, i="a-aaaaaaaaaaaa")
    signal.update(date="2026-10-28", direction="bullish", role="X account", link="https://x.com/a/status/1",
                  source_id="1", source_name="@a", horizon_days=21, posted_at="2026-10-28T09:00:00-07:00")
    doc = {"schema_version": 1, "date": "2026-10-28", "generated_at": "2026-10-28T09:00:00-07:00",
           "complete": True, "missing": [], "counts": {"signals": 1, "podcast": 0, "x": 1, "primary": 1, "recap": 0},
           "signals": [signal], **alpha_index.sentiment([signal], {"AAA": {"@b", "@c"}})}
    (pub / "2026-10-28.json").write_text(json.dumps(doc))
    for f in sorted(pub.glob("*.json")):
        d = json.loads(f.read_text())
        assert d["tickers"] and d["markets"] is not None and alpha_index.check(d, pub.parent) == [], f.name
        assert all(r["label"] in ("Mixed", "Neutral") or r["bull"] + r["bear"] == r["speakers"] or r["neutral"] >= 0 for r in d["tickers"])
        assert [r["rank"] for r in d["tickers"]] == sorted((r["rank"] for r in d["tickers"]), reverse=True)
        known = {s["id"] for s in d["signals"]}
        assert all(set(r["signal_ids"]) <= known and not r["ticker"].startswith("@") for r in d["tickers"])
    # a tampered row is caught by the check: an unknown signal id, an unknown label
    d = json.loads((pub / "2026-10-28.json").read_text())
    d["tickers"][0]["signal_ids"] = ["a-000000000000"]
    assert alpha_index.check(d, pub.parent)
    d = json.loads((pub / "2026-10-28.json").read_text())
    d["tickers"][0]["label"] = "Moonshot"
    assert alpha_index.check(d, pub.parent)
    # neutral voters: a speaker with only 0 labels counts once, a speaker who also has a signal does not count twice
    out = alpha_index.sentiment([sig("AAA", "@a", 1)], {"AAA": {"@a", "@b", "@c"}})
    assert (out["tickers"][0]["speakers"], out["tickers"][0]["neutral"]) == (1, 2)


def test_the_site_shows_the_x_aggregate_on_the_tape_the_day_page_and_the_sentiment_column(tmp_path):
    """stated-rule (the owner's brief): the tape scrolls 'TICKER ▲ Bullish' items only, and the Sentiment page carries an X column next to Net, which stays."""
    from wire import site
    pub, out = tmp_path / "published", tmp_path / "out"
    from tests.test_site import make_published
    make_published(pub)
    (pub / "alpha").mkdir()
    sigs = [sig("AAA", "@a", 2, i="a-aaaaaaaaaaa1"), sig("AAA", "@b", 1, i="a-aaaaaaaaaaa2"), sig("BBB", "@a", 1, i="a-bbbbbbbbbbb1"), sig("BBB", "@b", -1, i="a-bbbbbbbbbbb2"),
            sig("CCC", "@c", -2, i="a-ccccccccccc1"), sig("@RATES", "@a", 1, i="a-rrrrrrrrrrr1")]
    for s in sigs:
        s.update(date="2026-01-09", direction="bullish" if s["stance"] > 0 else "bearish", role="X account", link="https://x.com/a/status/1", source_id="1",
                 source_name=s["speaker"], horizon_days=21)
    day = {"schema_version": 1, "date": "2026-01-09", "generated_at": "2026-01-09T09:00-08:00", "complete": True, "missing": [],
           "counts": {"signals": 6, "primary": 6, "recap": 0}, "signals": sigs}  # no tickers[]: the site falls back to the same rule
    (pub / "alpha" / "2026-01-09.json").write_text(json.dumps(day))
    site.build(pub, out)
    home = (out / "index.html").read_text()
    tape = home[home.index('<span class="tape"'):].split("</summary>")[0]
    first = tape.split('<span class="tape-seq"', 2)[1]
    assert "AAA" in first and "strongly bullish" in first and "▲▲" in first and ">Bullish<" in first and "BBB" in first and "Mixed" in first and "CCC" in first and "@RATES" not in first
    assert 'href="/alpha/2026-01-09/#s-BBB"' in first and "◆" in first and "▼" in first and "▲" in first
    page = (out / "alpha" / "2026-01-09" / "index.html").read_text()
    assert 'id="s-AAA"' in page and 'id="s-BBB"' in page and "X sentiment by ticker" not in page and "Sentiment by ticker" not in page  # one card per ticker
    card = lambda t: page[page.index(f'id="s-{t}"'):].split("</details>")[0]  # line 1 is ticker, arrow, label, one tally; line 2 is what was said; then the posts
    top = lambda t: card(t).split("</summary>")[0]
    assert " Mixed</span>" in top("BBB") and "· 1/1" in top("BBB") and "· 2/2" in top("AAA") and 'class="lc"' in top("CCC") and 'class="card lo"' not in page
    assert 'class="card"' in page[:page.index('id="s-AAA"')].rsplit("<details", 1)[1]
    assert "@a on BBB" in top("BBB") and "▲" in top("BBB") and "▼" in top("BBB") and '<ul class="posts">' in card("BBB") and 'href="https://x.com/a/status/1"' in card("BBB")
    assert "Mixed Mixed" not in re.sub(r"<[^>]+>", " ", page) and "speakers (" not in page and "no call" not in page and "confidence" not in top("BBB")
    assert top("AAA").lower().count("bullish") == 1  # the label is said once
    assert page.count('id="s-BBB"') == 1 and page.index("<h2>Daily picks</h2>") < page.index('id="s-AAA"') < page.index("<h2>Markets</h2>") < page.index('id="s-RATES"')
    assert "Lower rates" in card("RATES") and "▲" in top("RATES")  # rates read as what is expected of them
    md = (out / "alpha" / "2026-01-09.md").read_text()
    assert "## Daily picks" in md and "### AAA: Strongly bullish 2/2" in md and "### BBB: Mixed 1/1" in md and "## X sentiment by ticker" not in md
    # the Sentiment page: the X column next to Net, a ticker with a board row gets its read, one without goes under 'X on ...'
    row = lambda t, net: {"ticker": t, "name": t + " Inc", "net": net, "bull": 1.0, "bear": 0.0, "mentions": 2, "sources": 1, "last": "2026-01-09", "items": []}
    sc = {"as_of": "2026-01-09", "rows": [row("AAA", 0.8), row("BBB", 0.0)], "market": []}
    xs = {"day": "2026-01-09", "tickers": site.alpha_sentiment.aggregate(sigs), "markets": site.alpha_sentiment.aggregate(sigs, market=True)}
    html = site.board_html(sc, {}, xs)
    assert html.count('class="bx pos"') == 1 and html.count('class="bx mix"') >= 1 and "▲▲ Bullish <span class=\"tl\">2/2</span>" in html and "◆ Mixed <span class=\"tl\">1/1</span>" in html
    assert "X Jan 9" in html and "+0.8" in html and "Net" in html and "X on Jan 9: 1 other ticker without a board row" in html and "CCC" in html
    md = site.board_md(sc, {}, xs)
    assert "net +0.8" in md and "X 2026-01-09: Strongly bullish 2/2" in md and "tickers without a board row" in md and "- CCC Strongly bearish 1/1" in md
    assert 'class="bx none"' in site.board_html(sc, {}, {"day": "2026-01-09", "tickers": [], "markets": []})
    assert "bx" not in site.board_md(sc, {}, None) and "X 20" not in site.board_md(sc, {}, None)


def test_the_tally_is_one_compact_figure_and_the_summary_says_what_was_said_once():
    """stated-rule (alpha_sentiment.py rule 9): 3/3 on a lean (leaders out of speakers with a view), bull/bear on a split; the reason never repeats the counts or label."""
    from wire import alpha_sentiment as a
    def say(t, who, st, text, origin="primary"):
        return {**sig(t, who, st, origin), "id": f"a-{abs(hash((t, who, text))) % 10**12:012x}", "reason": text}
    lean = one([say("AAA", "@a", 1, "Says its sold-out supply runs through 2029"), say("AAA", "@b", 2, "Memory supply is sold out for years"),
                say("AAA", "@c", 1, "Pricing power shows in the Q3 call")])
    assert a.tally(lean) == "3/3" and a.head(lean) == "▲ Bullish · 3/3" and "bullish" not in lean["reason"].lower() and not re.search(r"\d+ (of|speakers)", lean["reason"])
    assert lean["reason"].startswith("Memory supply is sold out for years") and lean["reason"].count(" · ") <= 1  # the near-duplicate claim is merged away
    bear = one([say("AAA", "@a", -1, "Rich multiple"), say("AAA", "@b", -1, "Guide looks soft"), say("AAA", "@c", 1, "Orders strong"), say("AAA", "@d", -2, "Weak cash conversion"),
                say("AAA", "@e", -1, "Inventory builds")])
    assert (bear["label"], a.tally(bear)) == ("Bearish", "4/5")  # 4 of the 5 speakers with a view are bearish
    split = one([say("AAA", "@a", 1, "Beat and raised guidance on strong orders"), say("AAA", "@b", -1, "Says a gap up into a downtrend is a good short")])
    assert split["label"] == "Mixed" and a.tally(split) == "1/1" and a.head(split) == "◆ Mixed · 1/1"
    assert split["reason"] == "▲ Beat and raised guidance on strong orders · ▼ A gap up into a downtrend is a good short"
    long = one([say("AAA", "@a", 1, "Pricing is firm across every contract tier, and buyers keep paying more for supply into next year")])
    assert len(long["reason"].split()) <= a.CLAIM_WORDS and "Mixed" not in long["reason"]
    assert one([say("AAA", "@a", 1, "Likes the setup; no explicit call")])["reason"] == "Likes the setup"


def test_an_opened_card_holds_official_embeds_with_only_a_link_a_fallback_list_and_a_podcast_line():
    from wire import alpha_site
    sig = lambda i, o="primary", kind="x", st=1: {"id": f"s{i}", "date": "2026-01-09", "ticker": "AAA", "target": "AAA", "stance": st, "speaker": f"@u{i}",
                                                  "origin": o, "source_kind": kind, "source_name": "Some Show" if kind == "podcast" else f"@u{i}",
                                                  "link": f"https://x.com/u{i}/status/{1000 + i}" if kind == "x" else "https://example.com/ep?t=5",
                                                  "reason": "Alpha words that must not be copied into the page body"}
    sigs = [sig(i, "recap" if i % 3 == 0 else "primary") for i in range(12)] + [sig(99, kind="podcast", st=-2), sig(0)]  # the last repeats a link
    r = alpha_site.alpha_sentiment.row("AAA", "AAA", [s for s in sigs if s["source_kind"] == "x"], 0)
    h = alpha_site.card(r, sigs)
    body = h.split("</summary>", 1)[1]
    assert body.count('<blockquote class="twitter-tweet" data-dnt="true"') == alpha_site.EMBED_MAX == 10 and body.count('class="tw-later"') == 2  # ten show, two wait
    assert 'data-theme="light"' in body and 'href="https://twitter.com/u1/status/1001">@u1</a></blockquote>' in body  # only the link inside the blockquote
    assert "Show 2 more" in body and "hidden" in body.split("Show 2 more")[0].rsplit("<button", 1)[1]
    assert "Alpha words" not in body and "recap" not in h.lower()  # no post text in the body; the origin label is gone from the human view
    assert body.count("<li>") == 12 and 'href="https://x.com/u1/status/1001"' in body and "▲" in body.split('<ul class="posts">')[1]  # the fallback list: one per post, stance arrow and handle
    assert '<p class="meta pods"><a href="https://example.com/ep?t=5"' in body and "▼▼ @u99, Some Show" in body
    js = alpha_site.EMBED_JS
    assert "platform.twitter.com/widgets.js" in js and "'toggle'" in js and "widgets.load" in js and js.count("platform.twitter.com") == 1
    assert "platform.twitter.com" not in h and "<script" not in h  # the script comes once per page, never per card
    assert "recap" not in alpha_site.card(r, sigs[:3]).lower() and "[post](" in alpha_site.post_md(sigs[0]) and "recap" not in alpha_site.post_md(sigs[0]).lower()
