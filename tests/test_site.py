"""`sigma site`: published/ in, the static website out. Rules come from AGENTS.md and the site notes, not from site.py."""
import html as _html
import json
import re

import pytest

from tests.helpers import private_hits
from sigma import research, site
from sigma.cli import main

EP = "rss:aaa"
THEMES = {  # the resolved form themes.py exports
    "week_of": "2026-01-05", "run": "2026-01-05-weekly", "headline": "Chip supply stays tight <b>all year</b>",
    "themes": [{"title": "Capacity <i>sold out</i>", "summary": "Two executives said capacity is booked and agreed on timing.",
                "stance": "consensus", "tickers": ["NVDA", "private:Acme"], "episode_ids": [EP, "rss:bbb"],
                "came_up_in": {"episodes": 2, "of": 5},
                "evidence": [{"episode_id": EP, "claim_index": 0, "claim": "Chips <b>sold</b> out", "speaker": "Jane <i>Doe</i>",
                              "show": "Show A", "episode_title": "Boss", "timestamp": 3725, "link": "https://example.com/e?t=3725"},
                             {"episode_id": "rss:bbb", "claim_index": 0, "claim": "Orders are booked", "speaker": "Bo", "show": "Show B",
                              "episode_title": "U", "timestamp": 61, "link": None}]}]}


def make_published(root):
    """A weekly whose agent-written text is full of markup and a javascript: link."""
    d = root / "2026-01-05-weekly"
    d.mkdir(parents=True)
    claim = {"ticker": ["NVDA", "private:Acme"], "claim": "Chips <b>sold</b> out", "speaker": "Jane <i>Doe</i>",
             "timestamp": 3725, "novelty": 2, "verifiable": 1}
    ranked = {"week_of": "2026-01-05", "notes": "2 fetched", "episodes": [
        {"episode_id": EP, "title": "<script>alert(1)</script> Boss", "url": "https://example.com/e", "source": "Show A",
         "tier": 1, "published": "2026-01-04", "score": 8, "reason": "Because <em>x</em>", "claims": [claim], "rank": 1}]}
    (d / "ranked.json").write_text(json.dumps(ranked))
    (d / "episodes.json").write_text(json.dumps([
        {"episode_id": EP, "title": "t", "source": "Show A", "has_transcript": True},
        {"episode_id": "rss:bbb", "title": "u", "source": "Show B", "has_transcript": False}]))
    rows = [{"episode_id": EP, "title": "<script>alert(1)</script> Boss", "show": "Show A", "published": "2026-01-04",
             "date": "2026-01-04", "tier": 1, "speaker": "Jane <i>Doe</i>", "timestamp": 3725, "text": "Chips <b>sold</b> out",
             "tickers": ["NVDA", "private:Acme"], "novelty": 2, "verifiable": 1, "source": "ranked", "run": d.name, "score": 8,
             "url": "https://example.com/e", "youtube_url": None, "transcript_url": "https://example.com/t",
             "link": "https://example.com/e?t=3725"},
            {"episode_id": EP, "title": "x", "show": "Show A", "speaker": "Bob", "timestamp": 5, "text": "No tickers",
             "tickers": ["AMD"], "run": d.name, "link": "javascript:alert(1)"}]
    (d / "claims.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "themes.json").write_text(json.dumps(THEMES))


def make_daily(root):
    d = root / "2026-01-09-daily"
    d.mkdir(parents=True)
    (d / "selected.json").write_text(json.dumps({"episodes": [{"episode_id": "rss:ddd"}]}))
    (d / "report.json").write_text(json.dumps({"date": "2026-01-09", "title": "Daily agent run", "key_insights": ["x"],
                                               "episodes": [{"episode_id": "rss:ddd", "headline": "Chips are tight"}]}))
    row = {"episode_id": "rss:ddd", "title": "Daily Show Ep", "show": "Show D", "published": "2026-01-08", "speaker": "Sam",
           "timestamp": 61, "text": "Capacity is tight", "tickers": ["TSM"], "run": d.name, "url": "https://example.com/d",
           "link": "https://example.com/d?t=61"}
    inf_claim = {"episode_id": "rss:inf", "title": "Chart week", "show": "Show I", "published": "2026-01-08", "speaker": "host",
                 "timestamp": 95, "text": "Calls for a long above 180", "tickers": ["NVDA", "INFX"], "run": d.name, "url": "https://example.com/i",
                 "link": "https://example.com/i"}  # the library writes influencer claims to claims.jsonl too
    (d / "claims.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(inf_claim) + "\n")
    (d / "scores-influencer.json").write_text(json.dumps({"week_of": "2026-01-09", "rubric": 1, "episodes": [  # a 10 would top any ranking
        {"episode_id": "rss:inf", "title": "Chart week", "url": "https://example.com/i", "source": "Show I", "tier": 2, "published": "2026-01-08",
         "score": 10, "reason": "Levels on two names", "rank": 1,
         "claims": [{"ticker": ["NVDA", "INFX"], "claim": "Calls for a long above 180", "speaker": "host", "timestamp": 95}]}]}))
    (d / "episodes.json").write_text(json.dumps([
        {"episode_id": "rss:inf", "title": "Chart week", "source": "Show I", "style": "influencer", "has_transcript": True},
        {"episode_id": "rss:inf2", "title": "Unscored chart week", "source": "Show I", "style": "influencer"}]))


def make_people(root):
    d = root / "2026-01-12-daily"
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({"date": "2026-01-12", "episodes": [{"episode_id": "rss:eee", "headline": "AWS"}]}))
    base = {"episode_id": "rss:eee", "title": "Jassy on AWS", "show": "Show E", "published": "2026-01-11", "date": "2026-01-11",
            "run": d.name, "url": "https://example.com/e", "youtube_url": "https://www.youtube.com/watch?v=abc",
            "transcript_url": "https://www.youtube.com/watch?v=abc", "tier": 1, "novelty": 3, "verifiable": 2, "score": 9}
    rows = [{**base, "speaker": "Andy Jassy (Amazon CEO)", "timestamp": 1506, "text": "Capacity is sold out", "tickers": ["AMZN", "NVDA"],
             "link": "https://www.youtube.com/watch?v=abc&t=1506s"},
            {**base, "speaker": "host", "timestamp": 10, "text": "Welcome back", "tickers": [], "link": "https://example.com/e"}]
    (d / "claims.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def make_speakers(root):
    """One episode whose claims are attributed in every shape the agents write; only named people get a page."""
    d = root / "2026-01-13-daily"
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({"date": "2026-01-13", "episodes": [{"episode_id": "rss:fff", "headline": "Panel"}]}))
    who = ["Sam Altman", "host (Andrew Ross Sorkin)", "guest (Intel CTO Pushkar Ranade)", "host", "unknown (panelist)", "CNBC anchor",
           "analyst (New Street Research)", "SemiAnalysis analyst (Howie or Sherry Zhang)", None]
    rows = [{"episode_id": "rss:fff", "title": "Panel", "show": "Show F", "published": "2026-01-12", "run": d.name,
             "url": "https://example.com/f", "speaker": sp, "timestamp": 10 + n, "text": f"Line {n}", "tickers": [],
             "link": "https://example.com/f"} for n, sp in enumerate(who)]
    (d / "claims.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def visible(h: str) -> str:
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S)
    return _html.unescape(re.sub(r"<[^>]+>", " ", h))


def build(tmp_path, *extra):
    pub = tmp_path / "published"
    for make in (make_published, make_daily, make_people, make_speakers):
        make(pub)
    out = tmp_path / "dist"
    main(["site", "--out", str(out), "--published", str(pub), *extra])
    return out


@pytest.fixture(autouse=True)
def no_real_entities(tmp_path, monkeypatch):
    """`sigma site` reads entities.json from the repo; point it at an empty file so the fixture shows stay untagged."""
    (tmp_path / "entities.json").write_text("{}")
    monkeypatch.setattr(site, "ENTITIES_FILE", tmp_path / "entities.json")


def test_site_pages_are_safe_plain_and_linked(tmp_path, capsys):
    """What a reader, or an agent crawling llms.txt, finds: agent text is never trusted as HTML, no internal vocabulary
    reaches a page, every advertised file exists."""
    out = build(tmp_path)
    assert "[site] built 4 runs" in capsys.readouterr().out
    assert not (out / "tickers" / "Acme.html").exists() and not (out / "about.html").exists()  # private:Acme gets no page
    run = (out / "runs/2026-01-05-weekly/index.html").read_text()
    assert "<script>alert" not in run and "&lt;script&gt;alert(1)&lt;/script&gt;" in run
    assert "<b>sold</b>" not in run and "1:02:05" in run and "Week of Jan 5, 2026" in run and "Transcript" not in run
    assert "javascript:" not in (out / "tickers/AMD.html").read_text()  # a link the agent wrote with that scheme is dropped
    assert "Chips" in (out / "tickers/NVDA.html").read_text() and "No tickers" not in (out / "tickers/NVDA.html").read_text()
    assert "No tickers" in (out / "tickers/AMD.html").read_text()
    assert "<script>alert" not in (out / "episodes/rss_aaa.html").read_text()
    dmd = (out / "runs/2026-01-09-daily.md").read_text()
    assert "Friday, Jan 9, 2026" in dmd and "Capacity is tight" in dmd and "0:01:01" not in dmd and "1:01" in dmd
    home = (out / "index.html").read_text()
    assert "Weekly issues" in home and "Daily issues" not in home and "Latest issue" not in home and "/runs/2026-01-09-daily/" not in home and 'href="/runs.json"' in home
    assert not private_hits(home) and '<a class="brand" href="/">Sigma</a>' in home
    banned = re.compile(r"\b(agents?|whisper|novelty|verifiable|tiers?|fetched|grounded|pipeline|transcripts?|2026-01-05-weekly|"
                        r"2026-01-09-daily|score|about)\b", re.I)
    for f in out.rglob("*.html"):
        text = visible(f.read_text())
        assert not banned.search(text), (f, banned.search(text).group(0))
    idx = json.loads((out / "runs.json").read_text())
    assert idx["runs"][-1] == {"run": "2026-01-05-weekly", "kind": "weekly", "date": "2026-01-05", "episodes": 1, "claims": 2,
                               "page": "/runs/2026-01-05-weekly/", "claims_path": "/runs/2026-01-05-weekly/claims.jsonl",
                               "themes_path": "/runs/2026-01-05-weekly/themes.json"}
    assert len((out / "claims.jsonl").read_text().splitlines()) == 2 + 1 + 2 + 9
    llms = (out / "llms.txt").read_text()
    assert llms.startswith("# Sigma\n\n> ") and "## Start here" in llms and "## Indexes" in llms
    links = re.findall(r"\]\((https://example\.invalid[^)]*)\)", llms)
    assert links
    for u in links:  # every link in llms.txt points at a file that was built
        assert (out / site.file_of(u.replace("https://example.invalid", ""))).exists(), u
    assert "/claims.jsonl" in llms and "/llms-full.txt" in llms and "/tickers/NVDA.md" in llms
    full = (out / "llms-full.txt").read_text()
    assert full.index("Jan 13, 2026") < full.index("Jan 12, 2026") < full.index("Jan 9, 2026") < full.index("Week of Jan 5, 2026")
    assert "Capacity is sold out — **Andy Jassy (Amazon CEO)**, [25:06](https://www.youtube.com/watch?v=abc&t=1506s)" in full
    for f in out.rglob("*.html"):  # every page has a Markdown twin, announced in its head
        if f.name.endswith(".claims.html"):  # bare fragments a home-page row loads, not pages
            continue
        rel = "/" + f.relative_to(out).as_posix()
        url = "/" if rel == "/index.html" else rel[:-len("index.html")] if rel.endswith("/index.html") else rel
        assert (out / site.file_of(site.md_of(url))).exists(), f
        assert f'<link rel="alternate" type="text/markdown" href="{site.md_of(url)}">' in f.read_text(), f
    for f in list(out.rglob("*.md")) + [out / "llms.txt", out / "llms-full.txt"]:
        text = f.read_text()
        assert not re.search(r"\b(novelty|verifiable|score|tier)\b", text, re.I), f
        assert "javascript:" not in text and not re.search(r"(?<!\\)<script", text), f
    sm = (out / "sitemap.xml").read_text()
    locs = re.findall(r"<loc>([^<]+)</loc>", sm)
    assert "https://example.invalid/tickers/" not in locs and "https://example.invalid/board/" not in locs
    for old in ("tickers", "board"):
        assert 'content="0; url=/sentiment/"' in (out / old / "index.html").read_text() and "/sentiment.md" in (out / f"{old}.md").read_text()
    assert 'href="/sentiment/" aria-current="page">Sentiment</a>' in (out / "sentiment/index.html").read_text()
    for path in ["/", "/index.md", "/sentiment/", "/sentiment.md", "/tickers/NVDA.html", "/people/andy-jassy.md", "/episodes/rss_eee.html",
                 "/runs/2026-01-12-daily.md", "/llms.txt"]:
        assert "https://example.invalid" + path in locs, path
    assert "<lastmod>2026-01-11</lastmod>" in sm and len(locs) == len(set(locs))
    robots = (out / "robots.txt").read_text()
    assert "Disallow" not in robots and "Sitemap: https://example.invalid/sitemap.xml" in robots


def test_site_people_shows_and_claim_ids(tmp_path):
    """Only named people get a page, claim ids are stable, absolute URLs follow --base-url."""
    out = build(tmp_path, "--base-url", "https://example.test/")
    rows = [json.loads(line) for line in (out / "claims.jsonl").read_text().splitlines()]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) == 14 and "2026-01-12-daily:rss:eee:1" in ids
    j = next(r for r in rows if r["id"] == "2026-01-12-daily:rss:eee:1")
    assert j["person"] == "Andy Jassy" and j["role"] == "Amazon CEO" and j["speaker"] == "Andy Jassy (Amazon CEO)"
    assert j["episode_page"] == "https://example.test/episodes/rss_eee.html" and j["person_page"] == "https://example.test/people/andy-jassy.html"
    assert j["ticker_pages"] == {"AMZN": "https://example.test/tickers/AMZN.html", "NVDA": "https://example.test/tickers/NVDA.html"}
    assert j["novelty"] == 3 and j["tier"] == 1  # the raw feed keeps the fields the pages hide
    assert next(r for r in rows if r["id"] == "2026-01-12-daily:rss:eee:2")["person"] is None  # "host" is a role, not a person
    assert not any(k.startswith("_") for r in rows for k in r)
    assert not private_hits((out / "llms.txt").read_text(), (out / "sitemap.xml").read_text())
    again = build(tmp_path / "again", "--base-url", "https://example.test/")
    assert ids == [json.loads(line)["id"] for line in (again / "claims.jsonl").read_text().splitlines()]
    ppl = json.loads((out / "people.json").read_text())["people"]
    assert sorted(p["name"] for p in ppl) == ["Andrew Ross Sorkin", "Andy Jassy", "Pushkar Ranade", "Sam Altman"]  # roles, firms, "Howie or Sherry" are not people
    jassy = next(p for p in ppl if p["slug"] == "andy-jassy")
    assert jassy["claims"] == 1 and jassy["roles"] == ["Amazon CEO"] and jassy["page"] == "https://example.test/people/andy-jassy.html"
    md = (out / "people/andy-jassy.md").read_text()
    assert md.startswith("# Andy Jassy\n") and "Role: Amazon CEO" in md and "Jassy on AWS" in md and "[25:06](" in md
    assert not list((out / "people").glob("host*")) and not (out / "people/unknown.html").exists()
    eps = json.loads((out / "episodes.json").read_text())["episodes"]
    e = next(x for x in eps if x["episode_id"] == "rss:eee")
    assert e["claims"] == 2 and e["issues"] == ["2026-01-12-daily"]
    assert next(x for x in eps if x["episode_id"] == "rss:bbb")["page"] is None  # listed, but it has no claims
    ep_md = (out / "episodes/rss_eee.md").read_text()
    assert "Welcome back" in ep_md and "Capacity is sold out" in ep_md and "[YouTube](https://www.youtube.com/watch?v=abc)" in ep_md
    shows = {s["show"]: s for s in json.loads((out / "shows.json").read_text())["shows"]}
    assert shows["Show E"]["claims"] == 2 and shows["Show E"]["episodes"][0]["episode_id"] == "rss:eee"
    show_html = (out / "shows/show-e.html").read_text()
    assert "Jassy on AWS" in show_html and "Capacity is sold out" in show_html and "Show B" not in show_html
    jassy_html = (out / "people/andy-jassy.html").read_text()
    assert '<a href="/shows/show-e.html">Show E</a>' in jassy_html and 'href="/episodes/rss_eee.html"' in jassy_html


ENTITIES = {
    "topic_groups": [{"id": "g", "name": "G", "topics": ["ai", "chips"]}], "topic_names": {"ai": "AI", "chips": "Chips"},
    "show_topics": {"show-e": ["ai", "chips", "bogus"]},
    "companies": {"amazon": {"name": "Amazon", "kind": "public", "ticker": "AMZN", "aliases": ["AWS"]}},
    "people": {"andy-jassy": {"name": "Andy Jassy", "affiliations": [{"company": "amazon", "role": "CEO"}]}},
    "lenses": {"signals": {"name": "Signals", "mark": "S", "about": "Public market signals", "topics": ["ai", "chips"], "public_ticker": 1}}}


def test_entities_filter_shows_companies_and_lenses(tmp_path):
    """Stated rules: shows are found by topic, an episode is found through the company it is about
    (a speaker's employer counts), and each episode carries only the public Signals lens."""
    pub = tmp_path / "published"
    make_published(pub)
    make_people(pub)
    one = pub / "2026-01-20-collection"
    one.mkdir()
    ranked = json.loads((pub / "2026-01-05-weekly" / "ranked.json").read_text())
    (one / "ranked.json").write_text(json.dumps({**ranked, "week_of": "2026-01-20", "title": "A chosen set"}))
    out = tmp_path / "dist"
    main(["site", "--out", str(out), "--published", str(pub)])
    assert 'id="chips"' not in (out / "shows/index.html").read_text() and "lensbar" not in (out / "index.html").read_text()  # no entities, no filters
    site.ENTITIES_FILE.write_text(json.dumps(ENTITIES))
    main(["site", "--out", str(out), "--published", str(pub)])
    index = (out / "shows/index.html").read_text()
    ai, chips, other = index.index('id="ai"'), index.index('id="chips"'), index.index('id="other"')
    assert ai < index.index("Show E") < chips < other < index.index("Show A")  # Show E under both tags, untagged last
    assert '<a href="/shows/?topic=chips#chips">Chips</a>' in (out / "shows/show-e.html").read_text()
    show_e = next(s for s in json.loads((out / "shows.json").read_text())["shows"] if s["show"] == "Show E")
    assert show_e["tags"] == ["ai", "chips"] and show_e["lenses"] == ["signals"]
    co = (out / "companies/amazon.html").read_text()  # Jassy's employer: the episode is about Amazon though he is the only speaker
    assert 'href="/episodes/rss_eee.html"' in co and 'href="/people/andy-jassy.html">Andy Jassy</a> (CEO)' in co
    assert '<a href="/companies/amazon.html">Amazon</a> · CEO' in (out / "people/andy-jassy.html").read_text()
    assert next(c for c in json.loads((out / "companies.json").read_text())["companies"] if c["id"] == "amazon")["episodes"] == 1
    rows = {e["i"]: e for e in json.loads((out / "find-index.json").read_text())["eps"]}
    assert rows["/episodes/rss_eee.html"]["c"] == ["amazon"] and rows["/episodes/rss_eee.html"]["l"] == ["signals"]
    assert rows["/episodes/rss_aaa.html"]["l"] == ["signals"]  # a public ticker claim, no AI topic
    assert 'data-l="signals"' in (out / "index.html").read_text() and 'data-lens="si"' not in (out / "index.html").read_text()
    home = (out / "index.html").read_text()
    assert "<h2>Special issues</h2>" in home and "A chosen set" in home and "Week of Jan 20" not in home
    tk = {t["symbol"]: t for t in json.loads((out / "tickers.json").read_text())["tickers"]}
    assert tk["NVDA"]["claims"] == 2 and tk["NVDA"]["latest_date"] == "2026-01-11" and tk["NVDA"]["md"] == "https://example.invalid/tickers/NVDA.md"


def test_podcasts_and_youtube_share_a_timestamp_sorted_feed_and_x_stays_separate(tmp_path):
    """Owner-stated rule: one newest-first podcast/video feed. Failure-seen: an editor-only interview advertised a missing expansion fragment."""
    site.ENTITIES_FILE.write_text(json.dumps(ENTITIES))
    pub = tmp_path / "published"
    for make in (make_published, make_daily, make_people, make_speakers):
        make(pub)
    weekly_path = pub / "2026-01-05-weekly" / "ranked.json"
    weekly = json.loads(weekly_path.read_text())
    weekly["episodes"][0]["published"] = "2026-01-09T20:30:00+00:00"
    weekly_path.write_text(json.dumps(weekly))
    claims_path = pub / "2026-01-05-weekly" / "claims.jsonl"
    claims = [json.loads(line) for line in claims_path.read_text().splitlines()]
    for claim in claims:
        if claim.get("episode_id") == EP:
            claim["published"] = "2026-01-09T20:30:00+00:00"
    claims_path.write_text("".join(json.dumps(claim) + "\n" for claim in claims))
    influencer_path = pub / "2026-01-09-daily" / "scores-influencer.json"
    influencer = json.loads(influencer_path.read_text())
    influencer["episodes"][0]["published"] = "2026-01-09T17:00:00+00:00"
    influencer["episodes"].extend([
        {"episode_id": "rss:inf4", "title": "Creator four", "source": "Show I", "published": "2026-01-09T18:00:00+00:00", "score": 4, "claims": []},
        {"episode_id": "rss:inf3", "title": "Creator three", "source": "Show I", "published": "2026-01-09T19:00:00+00:00", "score": 3, "claims": []},
    ])
    influencer_path.write_text(json.dumps(influencer))
    weekly_path = pub / "2026-01-05-weekly" / "ranked.json"
    weekly = json.loads(weekly_path.read_text())
    weekly["episodes"].extend([
        {"episode_id": "rss:pod4", "title": "Interview four", "source": "Show A", "published": "2026-01-09T18:30:00+00:00", "score": 4, "claims": []},
        {"episode_id": "rss:pod3", "title": "Interview three", "source": "Show A", "published": "2026-01-09T19:30:00+00:00", "score": 3, "claims": []},
    ])
    weekly_path.write_text(json.dumps(weekly))
    episodes_path = pub / "2026-01-09-daily" / "episodes.json"
    episodes = json.loads(episodes_path.read_text())
    creator_insights = [{"title": "Pricing limits", "text": "The creator distinguishes usage from revenue.",
                         "why_it_matters": "", "speaker": "Creator", "start": 1, "end": 3,
                         "companies": [], "inference": None}]
    creator_summary = [{"title": "Pricing", "text": "The discussion follows the limits on revenue conversion.",
                        "start": 0, "end": 5}]
    for episode in episodes:
        if episode.get("episode_id") == "rss:inf":
            episode["published"] = "2026-01-09T17:00:00+00:00"
            episode.update(key_insights=creator_insights, dense_summary=creator_summary)
    episodes.append({"episode_id": "rss:inf3", "title": "Creator three", "source": "Show I", "style": "influencer",
                     "published": "2026-01-09T19:00:00+00:00", "key_insights": creator_insights, "dense_summary": creator_summary})
    episodes.append({"episode_id": "rss:pod4", "title": "Interview four", "source": "Show A",
                     "published": "2026-01-09T18:30:00+00:00",
                     "key_insights": [{**creator_insights[0], "speaker": "Guest"}], "dense_summary": creator_summary})
    episodes_path.write_text(json.dumps(episodes))
    earnings = pub / "2026-01-09-earnings"
    earnings.mkdir()
    (earnings / "scores.json").write_text(json.dumps({"week_of": "2026-01-09", "rubric": 2, "episodes": []}))
    (earnings / "scores-influencer.json").write_text(json.dumps({"week_of": "2026-01-09", "rubric": 1, "episodes": [
        {"episode_id": "yt:amazon", "title": "Amazon earnings", "source": "Show I", "published": "2026-01-09T21:00:00+00:00",
         "url": "https://www.youtube.com/watch?v=amazon", "score": 8,
         "claims": [{"ticker": ["AMZN"], "claim": "Retail demand remains strong.", "speaker": "host", "timestamp": 20}]},
        {"episode_id": "yt:google", "title": "Google earnings", "source": "Show I", "published": "2026-01-10T01:02:32+00:00",
         "url": "https://www.youtube.com/watch?v=google", "score": 7,
         "claims": [{"ticker": ["GOOG"], "claim": "Cloud demand remains strong.", "speaker": "host", "timestamp": 30}]}]}))
    (earnings / "episodes.json").write_text(json.dumps([
        {"episode_id": "yt:amazon", "title": "Amazon earnings", "source": "Show I", "style": "influencer", "published": "2026-01-09T21:00:00+00:00"},
        {"episode_id": "yt:google", "title": "Google earnings", "source": "Show I", "style": "influencer", "published": "2026-01-10T01:02:32+00:00"}]))
    (earnings / "claims.jsonl").write_text("".join(json.dumps({"episode_id": eid, "title": title, "show": "Show I", "published": published,
        "run": earnings.name, "speaker": "host", "timestamp": 1, "text": title, "tickers": [], "link": ""}) + "\n"
        for eid, title, published in (("yt:amazon", "Amazon earnings", "2026-01-09T21:00:00+00:00"),
                                      ("yt:google", "Google earnings", "2026-01-10T01:02:32+00:00"))))
    editions = pub / "x" / "editions"
    editions.mkdir(parents=True)
    (editions / "2026-01-09.json").write_text(json.dumps({"date": "2026-01-09", "headline": "X edition", "signals": [], "posts": [
        {"id": "1", "handle": "someone", "cashtags": []}]}))
    out = tmp_path / "dist"
    main(["site", "--out", str(out), "--published", str(pub)])

    home = (out / "index.html").read_text()
    feed = home.split('<ol class="top" id="top">', 1)[1].split("</ol>", 1)[0]
    assert "Boss" in feed and "Chart week" in feed and "Amazon earnings" in feed and "Google earnings" in feed
    cards = re.findall(r'<li class="entry[^\"]*".*?</li>', feed, re.S)
    assert cards and all('class="epc-t"' in row and 'aria-expanded="false"' in row and 'class="epb"' in row and " hidden>" in row
                        for row in cards)
    google_row = next(row for row in cards if "Google earnings" in row)
    assert 'data-d="2026-01-09"' in google_row
    assert "Show I · Jan 9, 2026" in google_row
    assert f'data-src="{site.claims_path("yt:google")}"' in google_row and 'class="claims influencer"' not in google_row
    creator_without_claims = next(row for row in cards if "Creator four" in row)
    assert "No transcript claims are available." in creator_without_claims and 'aria-expanded="false"' in creator_without_claims
    podcast_without_claims = next(row for row in cards if "Interview four" in row)
    assert f'data-src="{site.claims_path("rss:pod4")}"' in podcast_without_claims and 'aria-expanded="false"' in podcast_without_claims
    editor_fragment = (out / site.file_of(site.claims_path("rss:pod4"))).read_text()
    assert "Pricing limits" in editor_fragment and "The creator distinguishes usage from revenue." in editor_fragment
    assert "The discussion follows the limits on revenue conversion." not in editor_fragment
    google_page = (out / site.file_of(site.episode_path("yt:google"))).read_text()
    assert "Show I · Jan 9, 2026" in google_page
    find_rows = {e["i"]: e for e in json.loads((out / "find-index.json").read_text())["eps"]}
    assert site.episode_path("yt:amazon") in find_rows and site.episode_path("yt:google") in find_rows, sorted(find_rows)
    assert site.episode_path(EP) in find_rows
    assert "Interview four" in feed and "Creator four" in feed
    assert "Interview three" not in feed and "Creator three" not in feed
    assert feed.index("Boss") < feed.index("Chart week")
    assert 'data-s="8"' in feed and 'data-s="10"' in feed
    assert 'data-s="4"' in feed
    assert "Rated 4 out of 10." in home and "worth an hour" not in home
    creator = site.creators.Creator("show-i", "Ivy Creator", ["show-i"])
    creator_videos, _ = site.creator_items(creator, {
        "four": {"id": "four", "score": 4, "show": "Show I"},
        "three": {"id": "three", "score": 3, "show": "Show I"},
    }, {}, {"show i": "show-i"})
    assert [e["id"] for e in creator_videos] == ["four"]
    assert '<option value="4">Rated 4+</option>' in (out / "find/index.html").read_text()
    nav = home.split('<nav aria-label="Main">', 1)[1].split("</nav>", 1)[0]
    assert 'href="/"' in nav and 'href="/x/">X</a>' in nav
    assert 'href="/sentiment/">Sentiment</a>' in nav and 'aria-label="Menu"' not in home
    social_redirect = (out / "social" / "index.html").read_text()
    assert 'content="0; url=/"' in social_redirect
    assert "Moved to [the home page](/index.md)." in (out / "social.md").read_text()

    x_home = (out / "x" / "index.html").read_text()
    assert "X edition" in x_home and "Chart week" not in x_home and "Boss" not in x_home
    assert '<a href="/x/" aria-current="page"><span class="mark x"' in x_home
    for path in ("x/week/index.html", "x/archive/index.html", "x/2026-01-09/index.html"):
        page = (out / path).read_text()
        assert 'href="/x/" aria-current="page"><span class="mark x"' in page
        assert "Chart week" not in page and "Boss" not in page
    assert "Chart week" not in (out / "claims.jsonl").read_text() and "Calls for a long" not in (out / "llms-full.txt").read_text()
    assert not any(x["episode_id"] in ("rss:inf", "rss:inf2") for x in json.loads((out / "episodes.json").read_text())["episodes"])
    social_json = {e["episode_id"]: e for e in json.loads((out / "social/episodes.json").read_text())["episodes"]}
    assert social_json["rss:inf"]["key_insights"] == creator_insights
    assert social_json["rss:inf"]["dense_summary"] == creator_summary
    assert social_json["rss:inf"]["style"] == "influencer" and social_json["rss:inf"]["score"] == 10
    assert "rss:inf3" not in social_json and EP not in social_json
    assert "Show I" not in (out / "shows.json").read_text() and "Show I" not in (out / "episodes.md").read_text()
    assert "Chart week" not in (out / "runs/2026-01-09-daily.md").read_text()
    tickers = {t["symbol"]: t for t in json.loads((out / "tickers.json").read_text())["tickers"]}
    assert tickers["NVDA"]["claims"] == 2 and "INFX" not in tickers
    nvda = (out / "tickers/NVDA.html").read_text()
    assert "Calls for a long above 180" in nvda and nvda.index("Chips") < nvda.index("<h2>Social</h2>") < nvda.index("Calls for a long")
    assert "Calls for a long above 180" in (out / "tickers/INFX.html").read_text()
    episode = (out / "episodes/rss_inf.html").read_text()
    assert "Rated as social commentary" in episode and "Rated 10 out of 10 as social commentary." in episode
    assert "Unscored chart week" not in home
    assert "Social" in (out / "tickers/NVDA.md").read_text() and "Calls for a long above 180" in (out / "tickers/NVDA.md").read_text()
    home_md = (out / "index.md").read_text()
    assert "Creator four" in home_md and "Creator three" not in home_md


def test_updated_line_is_pacific_time(monkeypatch):
    """'Updated Oct 27, 9:12 PM PT'. Worked by hand: Pacific is UTC-7 in October (daylight time) and UTC-8 in January; a date alone stays a date."""
    monkeypatch.setattr(site, "SITE_YEAR", 2026)  # the build sets it to the newest data's year, which is then left off
    assert site.updated_text("2026-10-27T02:26:20Z") == "Updated Oct 26, 7:26 PM PT"
    assert site.updated_text("2026-01-13T03:30:00Z") == "Updated Jan 12, 7:30 PM PT"
    assert site.updated_text("2026-10-26") == "Updated Oct 26"


def test_creator_page_lists_videos_and_x_posts_with_a_view_and_is_linked_from_both(tmp_path, monkeypatch):
    """A creator page joins their YouTube videos and X posts; the home feed links to it and a post's handle links back."""
    (tmp_path / "sources.yaml").write_text("sources:\n  - {id: show-i, name: Show I, tier: 2, style: influencer, youtube: 'https://y.example/c'}\n")
    (tmp_path / "creators.json").write_text(json.dumps({"creators": [{"id": "show-i", "name": "Ivy Creator", "sources": ["show-i"], "x": ["Someone"]}]}))
    monkeypatch.setattr(site, "SOURCES_FILE", tmp_path / "sources.yaml")
    monkeypatch.setattr(site, "CREATORS_FILE", tmp_path / "creators.json")
    pub = tmp_path / "published"
    (pub / "x/stances").mkdir(parents=True)
    (pub / "x/editions").mkdir()
    rows = [{"key": f"p-{i}", "labels": [{"ticker": t, "stance": s, "reason": "r"}], "id": i, "handle": "someone", "date": "2026-01-10"}
            for i, t, s in (("11", "NVDA", 1), ("12", "AMD", 0))]
    (pub / "x/stances/2026-01-10.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (pub / "x/editions/2026-01-10.json").write_text(json.dumps({"date": "2026-01-10", "headline": "A day", "signals": [], "posts": [
        {"id": "11", "handle": "someone", "cashtags": []}]}))
    out = build(tmp_path)
    h = (out / "creators/show-i.html").read_text()
    assert "<h1>Ivy Creator</h1>" in h and "Chart week" in h and 'href="https://x.com/someone/status/11"' in h and "/status/12" not in h
    assert h.index("/status/11") < h.index("Chart week") and 'href="/tickers/NVDA.html"' in h  # Jan 10 before Jan 8
    assert 'href="/creators/show-i.html">Show I</a>' in (out / "index.html").read_text()
    assert 'href="/creators/show-i.html">@someone</a>' in (out / "x/2026-01-10/index.html").read_text()
    assert "@someone on X" in (out / "creators/show-i.md").read_text() and "/creators/show-i.md" in (out / "sitemap.xml").read_text()


def test_a_claim_with_a_raw_u2028_in_its_text_is_still_read(tmp_path):
    """failure-seen (the scanner's first X scan; reproduced on site.read_jsonl): json.dumps(ensure_ascii=False) writes U+2028
    raw, str.splitlines() breaks the line there, and the half-line fails to parse and is skipped: the claim vanished from the site."""
    p = tmp_path / "claims.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in ({"id": 1, "text": "a\u2028b"}, {"id": 2, "text": "ok"})) + "\n", encoding="utf-8")
    assert [c["id"] for c in site.read_jsonl(p)] == [1, 2]


def test_home_lists_combined_feed_and_keeps_daily_issue_index_and_markdown(tmp_path):
    """The home lists the selected podcast and YouTube feed; run metadata and Markdown issue links remain available to agents."""
    out = build(tmp_path)
    home, md = (out / "index.html").read_text(), (out / "index.md").read_text()
    assert "<h2>Podcasts & YouTube</h2>" in home and "Latest issue" not in home and "Daily issues" not in home
    assert "## Podcasts & YouTube" in md and "/runs/2026-01-12-daily.md" in md
    assert (out / "runs/2026-01-12-daily.md").exists()
    assert "/runs/2026-01-12-daily/claims.jsonl" in (out / "runs.json").read_text()  # the agent index still lists the issue and its claims


def test_a_home_row_opens_to_its_timestamped_summaries_loaded_from_a_small_fragment(tmp_path):
    """Failure-seen (live home feed): every podcast and creator card has a closed detail control; claims load from small fragments."""
    out = build(tmp_path)
    home = (out / "index.html").read_text()
    rows = re.findall(r'<li class="entry[^"]*".*?</li>', home, re.S)
    assert rows and all(r.startswith('<li class="entry fold"') and 'class="epc-t"' in r and 'aria-expanded="false"' in r
                        and 'class="epb"' in r and " hidden>" in r for r in rows)
    assert all(re.search(r'<h3><a href="[^"]+">', r) for r in rows)
    creator_claims = next(r for r in rows if "Chart week" in r)
    assert 'class="claims influencer"' not in creator_claims and f'data-src="{site.claims_path("rss:inf")}"' in creator_claims
    srcs = re.findall(r'<div class="epb"[^>]*data-src="([^"]+)"[^>]*data-page="([^"]+)"', home)
    assert srcs and len({s for s, _ in srcs}) == len(srcs)
    for src, page in srcs:
        frag = (out / site.file_of(src)).read_text()
        assert frag.startswith('<ul class="claims') and 'class="ts"' in frag
        if src == site.claims_path("rss:inf"):
            assert frag.startswith('<ul class="claims influencer">')
        assert f'<a href="{page}">Open the episode page</a>' in frag
        claim = re.search(r"<li><p>(.*?)</p>", frag).group(1)
        assert claim not in home  # the summaries are not inlined
        assert claim in (out / site.file_of(page)).read_text()  # and they are the episode's own page's
    assert 'role="status"' in home and "li.fold" in home and "aria-expanded" in home  # the script and its status line ride with the rows
    assert 'content="0; url=/"' in (out / "social/index.html").read_text()
    assert ".claims" not in (out / "sitemap.xml").read_text() and ".claims" not in (out / "llms.txt").read_text()  # the fragments are not pages
    no_claims = site.top_entry({"id": "rss:z", "title": "No summaries", "page": "/episodes/rss_z.html", "claims": [], "date": "2026-01-01",
                                "published": "2026-01-01", "score": 8, "show": "S"}, expand=True)
    influencer = site.top_entry({"id": "rss:y", "title": "Creator video", "page": "/episodes/rss_y.html", "claims": [{"person": "P"}], "date": "2026-01-01",
                                 "published": "2026-01-01", "score": 8, "show": "S", "influencer": True}, expand=True)
    assert 'class="entry fold"' in no_claims and 'aria-expanded="false"' in no_claims and "No transcript claims are available." in no_claims
    assert '<a href="/episodes/rss_z.html">No summaries</a>' in no_claims
    assert 'class="entry fold"' in influencer and 'aria-expanded="false"' in influencer and 'data-src="/episodes/rss_y.claims.html"' in influencer
    assert '<ul class="claims influencer">' not in influencer and '<a href="/episodes/rss_y.html">Creator video</a>' in influencer


def test_every_run_the_site_builds_passes_verify_and_no_issue_address_dangles(tmp_path, monkeypatch):
    """failure-seen: release reviews found `sigma verify --run` failing on healthy sites (a weekly; a `-daily` name), and the site
    sending a daily issue's address to a home-page day with no row (2026-01-09-daily and 2026-01-12-daily here: their episodes
    came out the day before). Stated rule (owner, 2026-10-28): a daily issue's address lands on its day on the home page."""
    from sigma import verify

    pub = tmp_path / "published"
    special, day = pub / "2026-01-07-latent-space", pub / "2026-01-14"
    special.mkdir(parents=True)
    day.mkdir()
    (special / "ranked.json").write_text(json.dumps({"title": "Latent Space picks", "week_of": "2026-01-07", "episodes": [
        {"episode_id": "rss:sss", "title": "Agents", "source": "Show S", "published": "2026-01-03", "score": 7}]}))
    (day / "report.json").write_text(json.dumps({"date": "2026-01-14", "episodes": [{"episode_id": "rss:ggg", "headline": "Orders"}]}))
    (day / "scores.json").write_text(json.dumps({"episodes": [  # a 6+ that came out the day of the issue: home has that day
        {"episode_id": "rss:ggg", "title": "Same day", "source": "Show G", "published": "2026-01-14", "score": 7}]}))
    (day / "claims.jsonl").write_text(json.dumps({
        "episode_id": "rss:ggg", "title": "Same day", "show": "Show G", "published": "2026-01-14", "run": day.name,
        "speaker": "Kim", "timestamp": 5, "text": "Orders doubled", "tickers": [], "url": "https://example.com/g"}) + "\n")
    creator = pub / "2026-01-14-extra"
    creator.mkdir()
    (creator / "ranked.json").write_text(json.dumps({"week_of": "2026-01-12", "episodes": []}))
    (creator / "scores-influencer.json").write_text(json.dumps({"episodes": [
        {"episode_id": "yt:creator", "title": "Creator picks", "source": "Creator", "published": "2026-01-14", "score": 7}]}))
    out = build(tmp_path)

    def get(url):
        f = out / site.file_of(url.removeprefix("https://w.test"))
        return (200, f.read_text(), 1, "") if f.is_file() else (404, "", 1, "")

    monkeypatch.setattr(verify, "get", get)
    runs = [r["run"] for r in json.loads((out / "runs.json").read_text())["runs"]]
    assert {"2026-01-05-weekly", "2026-01-07-latent-space", "2026-01-14", "2026-01-09-daily", "2026-01-12-daily"} <= set(runs)
    creator_run = next(r for r in json.loads((out / "runs.json").read_text())["runs"] if r["run"] == creator.name)
    assert (creator_run["kind"], creator_run["date"]) == ("daily", "2026-01-14")
    for run in runs:
        main(["verify", "https://w.test/", "--run", run])  # exits on any problem
    assert 'url=/#d-2026-01-14"' in (out / "runs/2026-01-14/index.html").read_text()
    with pytest.raises(SystemExit):
        main(["verify", "https://w.test/", "--run", "2026-01-13-weekly"])


def test_signals_sits_beside_the_podcast_home_with_at_least_three_picks_and_agent_files(tmp_path):
    """The home page carries a collapsible Signals panel beside the combined podcast and YouTube feed; /signals/
    shows at least three picks (the weak ones labelled lower confidence), and agents get stable JSON, a schema, llms.txt and a
    Markdown twin. With no Signals data the home has no panel."""
    pub, out = tmp_path / "published", tmp_path / "dist"
    make_published(pub)
    site.build(pub, out)
    assert "<h2>Podcasts & YouTube</h2>" in (out / "index.html").read_text() and (out / "signals/index.html").exists() and "No signals are published yet" in (out / "signals/index.html").read_text() and "signals-panel" not in (out / "index.html").read_text()
    visible_routes = [path for path, _, _ in site.NAV_PRIMARY]
    visible_routes.extend(("/signals/",))
    assert all((out / site.file_of(path)).exists() for path in visible_routes)
    social = (out / "social/index.html").read_text()
    assert 'content="0; url=/"' in social
    assert "What the sources say, not advice." not in (out / "index.html").read_text()
    assert "Public market signals, each linked to its source." not in (out / "signals/index.html").read_text()
    sig = lambda t, who, st, o="primary": {"id": f"a-{t}{who}", "date": "2026-01-09", "ticker": t, "target": t, "direction": "bullish" if st > 0 else "bearish",
                                          "stance": st, "speaker": who, "role": "X account", "link": f"https://x.com/{who}/status/1", "source_kind": "x",
                                          "source_id": "1", "source_name": who, "origin": o, "horizon_days": 21, "reason": f"Likes {t}"}
    sigs = [sig("AAA", "@a", 2), sig("AAA", "@b", 1), sig("BBB", "@a", 1, "recap"), sig("CCC", "@c", -1), sig("DDD", "@d", 1), sig("@MARKET", "@e", 1),
            {**sig("ZZZ", "Host", 2), "source_kind": "podcast", "link": "https://example.com/ep", "source_name": "Some Show"}]
    (pub / "signals").mkdir()
    day = {"schema_version": 1, "date": "2026-01-09", "generated_at": "2026-01-09T09:00-08:00", "complete": False,
           "missing": [{"source": "x", "reason": "2 posts unlabelled"}], "counts": {"signals": 7, "primary": 6, "recap": 1}, "signals": sigs}
    (pub / "signals" / "2026-01-09.json").write_text(json.dumps(day))
    (pub / "x/editions").mkdir(parents=True)
    (pub / "x/editions/2026-01-09.json").write_text(json.dumps({"date": "2026-01-09", "headline": "A day", "signals": [], "posts": []}))
    site.build(pub, out)
    for xp in ("x/index.html", "x/2026-01-09/index.html"):  # the old X pages open with the Signals view and keep the edition under it
        xh = (out / xp).read_text()
        assert xh.count('class="card') >= 3 and xh.index('class="card') < xh.index("<h2>A day</h2>")
    assert "Daily picks" in (out / "x.md").read_text() and "\n## A day" in (out / "x.md").read_text()
    home = (out / "index.html").read_text()
    assert "<h2>Podcasts & YouTube</h2>" in home and '<details class="signals-panel" id="signals-panel" open>' in home and "All of today" in home
    # the panel and its tape hold X signals only, say so with the X mark, and link each ticker to its signal on the day page
    assert 'aria-label="X signals"' in home and 'class="tape"' in home and 'href="/signals/2026-01-09/#s-AAA"' in home
    assert "ZZZ" not in home[home.index('<details class="signals-panel"'):] .split("</details>")[0] and "ZZZ" in (out / "signals" / "index.html").read_text()
    tape = home[home.index('<span class="tape"'):].split("</summary>")[0]
    tape = re.sub(r"<[^>]+>", " ", tape)  # the visible words only. The tape scrolls per-ticker items only: no date, count or market line
    assert "X signal" not in tape and "Jan" not in tape and "US stocks" not in tape and "@MARKET" not in tape and "▲" in tape
    assert "AAA" in tape and "Bullish" in tape and "ZZZ" not in tape
    assert "tabindex=\"-1\"" in home and "prefers-reduced-motion" in (out / "style.css").read_text()
    assert 'id="s-AAA"' in (out / "signals" / "2026-01-09" / "index.html").read_text() and 'id="s-MARKET"' in (out / "signals" / "2026-01-09" / "index.html").read_text()
    signals = (out / "signals" / "index.html").read_text()
    picks_html = signals.split("<h2>Daily picks")[1].split("<h2>Markets")[0]
    assert picks_html.count('<details class="card') >= 3 and 'class="lc"' in picks_html and 'class="card lo"' not in signals and "Incomplete day" in signals and "Lower confidence" not in signals and "recap" not in re.sub(r"<script.*?</script>|<style.*?</style>", "", signals).lower()  # the weak picks carry a dim dot, not a fade; the origin label is JSON only
    assert "primary" not in picks_html and "<h2>More from today</h2>" in signals
    assert 'data-rest="/signals/2026-01-09/rest.html"' in signals and 'href="/signals/2026-01-09/more/"' in signals  # a link without a script, a toggle with one
    frag = (out / "signals" / "2026-01-09" / "rest.html").read_text()
    rest_ids = re.findall(r'id="(s-\w+)"', frag)  # the rest is in the fragment and the no-script page, and not in the day page itself
    assert rest_ids and "<html" not in frag and all(f'id="{i}"' not in signals for i in rest_ids)
    more = (out / "signals" / "2026-01-09" / "more" / "index.html").read_text()
    assert all(f'id="{i}"' in more for i in rest_ids) and "/more/" not in (out / "sitemap.xml").read_text() and 'class="card lo"' not in frag
    assert 'url=/' in (out / "podcasts" / "index.html").read_text() and (out / "podcasts.md").exists()
    assert json.loads((out / "signals" / "index.json").read_text())["days"][0]["path"] == "/signals/2026-01-09.json"
    assert (out / "signals" / "2026-01-09.json").exists() and (out / "signals" / "schema.json").exists() and (out / "research" / "index.html").exists()
    assert "/signals/index.json" in (out / "llms.txt").read_text() and "Daily picks" in (out / "signals.md").read_text() and "signals.md" in (out / "index.md").read_text()
    assert "/signals/2026-01-09.json" in (out / "sitemap.xml").read_text()


def test_research_posts_are_allowlisted_safe_and_fail_before_replacing_site(tmp_path, monkeypatch):
    data = tmp_path / "data"
    posts_dir = data / "research" / "posts"
    posts_dir.mkdir(parents=True)
    (data / "research" / "index.json").write_text(json.dumps({"posts": ["agent-workflows"]}))
    post = {"title": "Public agent workflows", "date": "2026-10-01", "summary": "A synthetic methods note.",
            "body": "Public agent workflows and model prompts use explicit, inspectable steps.\n\n<script>alert(1)</script> They can be compared without disclosing private inputs."}
    (posts_dir / "agent-workflows.json").write_text(json.dumps(post))
    allowed = research.load(data)
    assert [item["slug"] for item in allowed] == ["agent-workflows"]
    pages = {}
    sitemap = []
    out = tmp_path / "dist"
    site.research_post_pages(allowed, lambda path, page, md, updated="": pages.update({path: (page, md)}), out, sitemap)
    html_page, markdown = pages["/research/agent-workflows/"]
    assert "Public agent workflows" in html_page and "inspectable steps" in html_page
    assert "<script>alert(1)</script>" not in html_page and "&lt;script&gt;alert(1)&lt;/script&gt;" in html_page and "# Public agent workflows" in markdown
    assert json.loads((out / "research/agent-workflows.json").read_text()) == {"slug": "agent-workflows", **post}
    assert sitemap == [("/research/agent-workflows.json", "2026-10-01")]

    monkeypatch.setenv("SIGMA_DATA_ROOT", str(data))
    (out / "index.html").write_text("previous valid site")
    key_markers = ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "OPENSSH PRIVATE KEY", "ENCRYPTED PRIVATE KEY", "DSA PRIVATE KEY")
    blocked = ["Fair value estimate.", "Internal system prompt.", "BLOB_READ_WRITE_TOKEN in private notes.",
               "VERCEL_BLOB_RW_store123_secret123", "sk_test_0123456789abcdef", "I own 1200 shares of NVDA."]
    blocked.extend(("our\nportfolio: NVDA 25%", "our\tportfolio: NVDA 25%",
                    '{"DATABASE_PASSWORD": "synthetic-example-123"}'))
    blocked.extend(f"-----BEGIN {marker}-----\nsynthetic placeholder\n-----END {marker}-----" for marker in key_markers)
    for text in blocked:
        post["body"] = text
        (posts_dir / "agent-workflows.json").write_text(json.dumps(post))
        with pytest.raises(ValueError, match="not publishable") as exc:
            site.build(tmp_path / "published", out)
        assert "DATABASE_PASSWORD" not in str(exc.value) and "synthetic-example-123" not in str(exc.value)
        assert (out / "index.html").read_text() == "previous valid site"


def test_research_only_publishes_explicit_slugs(tmp_path):
    research_dir = tmp_path / "research"
    (research_dir / "posts").mkdir(parents=True)
    (research_dir / "index.json").write_text(json.dumps({"posts": []}))
    (research_dir / "posts" / "unlisted.json").write_text(json.dumps({"body": "not included"}))
    assert research.load(tmp_path) == []
    (research_dir / "index.json").write_text(json.dumps({"posts": ["../unlisted"]}))
    with pytest.raises(ValueError, match="invalid or duplicate"):
        research.load(tmp_path)
