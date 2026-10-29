"""`sigma site`: published/ in, the static website out. Rules come from AGENTS.md and the site notes, not from site.py."""
import html as _html
import json
import re

import pytest

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
    assert "@dming" not in home and "Mingdom" not in home and '<a class="brand" href="/">Sigma</a>' in home
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
    assert "dming" not in (out / "llms.txt").read_text() and "dming" not in (out / "sitemap.xml").read_text()
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


def test_influencer_episodes_are_social_videos_and_never_enter_the_ranking(tmp_path):
    """Social is a top-level section, Videos | X, not part of Podcasts. An influencer episode scored 10 stays out of the
    Top list, the claims feed, shows, people and every count; it is listed on /social/ (newest first) and its Markdown twin. Podcasts is Deep only."""
    site.ENTITIES_FILE.write_text(json.dumps(ENTITIES))
    out = build(tmp_path)
    home = (out / "index.html").read_text()
    assert "Chart week" not in home and 'data-kind' not in home and 'class="kindbar"' not in home and 'id="social"' not in home
    assert 'data-list="top" data-default="newest" data-key="top-2"' in home and 'data-s="8"' in home  # the home list opens on Newest; Rating is one click away
    social = (out / "social/index.html").read_text()
    assert "Chart week" in social and "Calls for a long above 180" in social and 'data-list="social" data-default="newest"' in social
    assert "Rated 10 out of 10 as social commentary." in social and "worth an hour" not in social
    assert '<a href="/social/" aria-current="page">Social</a>' in social and '<a href="/social/" aria-current="page"><span class="mark social"' in social
    assert "Chart week" not in (out / "claims.jsonl").read_text() and "Calls for a long" not in (out / "llms-full.txt").read_text()
    assert not any(x["episode_id"] in ("rss:inf", "rss:inf2") for x in json.loads((out / "episodes.json").read_text())["episodes"])
    assert "Show I" not in (out / "shows.json").read_text() and "Show I" not in (out / "episodes.md").read_text()
    assert "Chart week" not in (out / "runs/2026-01-09-daily.md").read_text()
    tk = {t["symbol"]: t for t in json.loads((out / "tickers.json").read_text())["tickers"]}
    assert tk["NVDA"]["claims"] == 2 and "INFX" not in tk  # the ticker index counts interview claims only
    nvda = (out / "tickers/NVDA.html").read_text()
    assert "Calls for a long above 180" in nvda and nvda.index("Chips") < nvda.index("<h2>Social</h2>") < nvda.index("Calls for a long")
    assert "Calls for a long above 180" in (out / "tickers/INFX.html").read_text()  # the chip links somewhere
    ep = (out / "episodes/rss_inf.html").read_text()
    assert "Rated as social commentary" in ep and "Rated 10 out of 10 as social commentary." in ep
    assert "Unscored chart week" not in social and "<h1>Social</h1>" in social and "<title>Social · Sigma</title>" in social
    assert (out / "social.md").read_text().startswith("# Social")
    assert "Rated 10/10 as social commentary. Levels on two names" in (out / "social.md").read_text()
    llms = (out / "llms.txt").read_text()
    assert "/social.md" in llms and "/social.md" in (out / "index.md").read_text()
    sm = (out / "sitemap.xml").read_text()
    assert all(f"https://example.invalid{p}" in sm for p in ("/social/", "/social.md", "/episodes/rss_inf.html", "/tickers/INFX.html"))
    assert "Social" in (out / "tickers/NVDA.md").read_text() and "Calls for a long above 180" in (out / "tickers/NVDA.md").read_text()
    (tmp_path / "published/2026-01-09-daily/scores-influencer.json").unlink()
    main(["site", "--out", str(tmp_path / "bare"), "--published", str(tmp_path / "published")])
    assert "<h1>Social</h1>" in (tmp_path / "bare/social/index.html").read_text()
    ed = tmp_path / "published/x/editions"
    ed.mkdir(parents=True)
    (ed / "2026-01-09.json").write_text(json.dumps({"date": "2026-01-09", "headline": "A day", "signals": [], "posts": [
        {"id": "1", "handle": "someone", "cashtags": []}]}))
    main(["site", "--out", str(tmp_path / "xonly"), "--published", str(tmp_path / "published")])
    for path in ("x/index.html", "x/week/index.html", "x/archive/index.html", "x/2026-01-09/index.html", "social/index.html"):  # Social is current on both sides
        h = (tmp_path / "xonly" / path).read_text()
        assert '<a href="/social/" aria-current="page">Social</a>' in h and '<a href="/" aria-current' not in h, path
        assert h.index('class="seg"') < h.index('class="xtabs"' if path.startswith("x/") else "<h1>"), path
    assert '<a href="/x/" aria-current="page"><span class="mark x"' in (tmp_path / "xonly/x/week/index.html").read_text()


def test_weekly_themes_lead_the_page_and_a_broken_file_never_breaks_it(tmp_path):
    out = build(tmp_path)
    html = (out / "runs/2026-01-05-weekly/index.html").read_text()
    assert html.index("Chip supply stays tight") < html.index("Capacity") < html.index('<article class="entry"')  # themes above the episodes
    assert "&lt;b&gt;all year&lt;/b&gt;" in html and "<b>all year</b>" not in html and "<i>sold out</i>" not in html
    text = " ".join(visible(html).split())
    assert "Consensus" in text and "Came up in 2 of 5 episodes" in text
    assert '<a class="chip" href="/tickers/NVDA.html">NVDA</a>' in html and "Acme" in text and 'href="/tickers/Acme' not in html
    assert '<a href="#ep-rss_aaa"' in html and ">Jane &lt;i&gt;Doe&lt;/i&gt;, Show A</a>" in html and 'id="ep-rss_aaa"' in html
    assert "<li>Bo, Show B</li>" in html and 'href="#ep-rss_bbb"' not in html  # an episode that is not on the page is not linked
    assert "Themes" not in (out / "runs/2026-01-12-daily.md").read_text() and 'id="theme-1"' in html
    home = (out / "index.html").read_text()
    # the home page leads with the top-scored episodes (score 6 or more), then the latest themes
    assert home.index('<ol class="top" id="top">') < home.index("Chip supply stays tight")
    # a bare number read as unexplained; then the text wrapped to a second row, so it is a bar first in the meta line with a hover explanation
    assert '<li class="entry fold" data-d="2026-01-04" data-l="" data-s="8" data-new id="d-2026-01-04">' in home and 'style="--n:8" role="img" tabindex="0" aria-label="Rated 8 out of 10. 6 or more is worth an hour of your time." data-tip="Rated 8 out of 10.' in home
    assert ">Rated 8/10<" not in home  # the bar carries the rating; its hover text says what it means
    # the home page says when it was last updated, from the newest daily (2026-01-13 here), and the Top list opens on Week.
    # that is the footer's one "Updated" line on every page, not a second marker beside the Top heading.
    assert '<p class="upd">Updated Jan 13</p>' in home and 'class="updated"' not in home and "let w='7'" in home
    for icon in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):  # the page head links these; a reader's tab shows no icon without them
        assert f'href="/{icon}"' in home and (out / icon).stat().st_size > 0
    assert "[hidden]{display:none!important}" in (out / "style.css").read_text()  # .entry sets display, which beat the attribute and left every row showing
    assert "sigma-window-2" in home and "sigma-window')" not in home  # the Month a first load once saved must not override Week
    assert '<a href="/runs/2026-01-05-weekly/#theme-1">Capacity &lt;i&gt;sold out&lt;/i&gt;</a>' in home and '<a href="/themes/">All themes' in home
    page = (out / "themes/index.html").read_text()
    assert 'href="/themes/" aria-current="page"' in page and "Week of Jan 5, 2026" in page
    assert '<a href="/runs/2026-01-05-weekly/#ep-rss_aaa"' in page
    assert "### Themes" in (out / "themes.md").read_text() and "[Themes](https://example.invalid/themes.md)" in (out / "index.md").read_text()
    md = (out / "runs/2026-01-05-weekly.md").read_text()
    assert md.index("## Themes") < md.index("Chip supply stays tight") < md.index("### Capacity") < md.index("Boss")
    assert "Consensus · Came up in 2 of 5 episodes · Tickers: [NVDA](https://example.invalid/tickers/NVDA.md), Acme (private)" in md
    assert "[1:02:05](https://example.com/e?t=3725)" in md and "<b>" not in md.replace("\\<b>", "")
    assert "[Themes as JSON](https://example.invalid/runs/2026-01-05-weekly/themes.json)" in md
    assert json.loads((out / "runs/2026-01-05-weekly/themes.json").read_text())["themes"][0]["came_up_in"] == {"episodes": 2, "of": 5}
    assert "### Themes" in (out / "llms-full.txt").read_text() and "/runs/<issue>/themes.json" in (out / "llms.txt").read_text()
    assert "Themes" not in (out / "runs/2026-01-09-daily.md").read_text()
    # a missing or broken themes.json leaves the issue as it was before themes existed
    pub = tmp_path / "published"
    d = pub / "2026-01-05-weekly"
    for content in ("{not json", json.dumps({"themes": []}), json.dumps([1]), None):
        if content is None:
            (d / "themes.json").unlink()
        else:
            (d / "themes.json").write_text(content)
        main(["site", "--out", str(tmp_path / "dist2"), "--published", str(pub)])
        assert "<h2>Themes</h2>" not in (tmp_path / "dist2/runs/2026-01-05-weekly/index.html").read_text()
        assert "themes_path" not in (tmp_path / "dist2/runs.json").read_text()
        assert not (tmp_path / "dist2/runs/2026-01-05-weekly/themes.json").exists()
    assert "No themes yet" in (tmp_path / "dist2/themes/index.html").read_text()


def test_updated_line_is_pacific_time(monkeypatch):
    """'Updated Oct 27, 9:12 PM PT'. Worked by hand: Pacific is UTC-7 in October (daylight time) and UTC-8 in January; a date alone stays a date."""
    monkeypatch.setattr(site, "SITE_YEAR", 2026)  # the build sets it to the newest data's year, which is then left off
    assert site.updated_text("2026-10-27T02:26:20Z") == "Updated Oct 26, 7:26 PM PT"
    assert site.updated_text("2026-01-13T03:30:00Z") == "Updated Jan 12, 7:30 PM PT"
    assert site.updated_text("2026-10-26") == "Updated Oct 26"


def test_creator_page_lists_videos_and_x_posts_with_a_view_and_is_linked_from_both(tmp_path, monkeypatch):
    """A creator is one page over their outlets: Social videos of their source and X posts of their handle that hold a view (a
    stance of 0 holds none), newest first, with no rating of the creator. The Social row and the post's handle link to it."""
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
    assert 'href="/creators/show-i.html">Show I</a>' in (out / "social/index.html").read_text()
    assert 'href="/creators/show-i.html">@someone</a>' in (out / "x/2026-01-10/index.html").read_text()
    assert "@someone on X" in (out / "creators/show-i.md").read_text() and "/creators/show-i.md" in (out / "sitemap.xml").read_text()


def test_a_claim_with_a_raw_u2028_in_its_text_is_still_read(tmp_path):
    """failure-seen (the scanner's first X scan; reproduced on site.read_jsonl): json.dumps(ensure_ascii=False) writes U+2028
    raw, str.splitlines() breaks the line there, and the half-line fails to parse and is skipped: the claim vanished from the site."""
    p = tmp_path / "claims.jsonl"
    p.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in ({"id": 1, "text": "a\u2028b"}, {"id": 2, "text": "ok"})) + "\n", encoding="utf-8")
    assert [c["id"] for c in site.read_jsonl(p)] == [1, 2]


def test_a_guest_on_several_shows_gets_one_top_row_and_a_host_never_folds_his_own_show():
    """stated-rule: of one person's many interviews in a week, show the best one."""
    def ep(eid, show, day, score, title, who):
        return {"id": eid, "show": show, "title": title, "date": f"2026-10-{day:02d}", "published": f"2026-10-{day:02d}", "score": score,
                "tier": 1, "page": f"/episodes/{eid}.html", "claims": [{"person": who, "_person_slug": site.person_slug(who)}]}
    reg = {e["id"]: e for e in [
        ep("best", "Show A", 20, 9, "Eric Schmidt on agents", "Eric Schmidt"),
        ep("other", "Show B", 25, 7, "Eric Schmidt scores the AI race", "Eric Schmidt"),
        ep("late", "Show C", 28, 8, "Eric Schmidt again", "Eric Schmidt"),  # within 14 days of "best"
        ep("old", "Show D", 1, 7, "Eric Schmidt at Davos", "Eric Schmidt"),  # 19 days before "best": its own row
        ep("h1", "Show E", 21, 7, "Weekly with Pat Host", "Pat Host"),
        ep("h2", "Show E", 22, 6, "More weekly with Pat Host", "Pat Host")]}  # same show as h1: never folded
    rows = re.findall(r'<li class="entry[^"]*".*?</li>', site.top_html(reg), re.S)
    assert [re.search(r'data-src="/episodes/(\w+)\.claims\.html"', r).group(1) for r in rows] == ["h2", "h1", "best", "old"]  # newest first; the fold is the same
    assert "Also with Eric Schmidt: " in rows[2] and rows[2].count('<a href="/episodes/') == 3


def test_home_opens_on_newest_says_when_it_was_updated_and_a_daily_issue_address_lands_on_its_day(tmp_path):
    """Stated rule (owner, 2026-10-28): no separate latest-issue page; the home opens on Newest, says an update is there, and marks the new rows.
    The first row of each day has an id, an old daily issue's address redirects to it, and its Markdown twin stays for agents."""
    out = build(tmp_path)
    home, md = (out / "index.html").read_text(), (out / "index.md").read_text()
    day = re.search(r'id="top-status" data-date="([\d-]+)"', home).group(1)
    assert "Last update" in home and "Updated today" in home and f'id="d-{day}"' in home and 'data-new' in home  # the script upgrades the text on the day itself
    assert home.count("data-new") >= 1 and all(f'data-d="{day}"' in r for r in re.findall(r'<li class="entry"[^>]*data-new[^>]*>', home))  # only the newest day is marked
    assert "Latest issue" not in home and "Daily issues" not in home and "hash.match" in home
    assert "## Newest episodes" in md and "Latest:" not in md and "**new**" in md and "/runs/2026-01-12-daily.md" in md
    assert (out / "runs/2026-01-12-daily.md").exists()
    assert "/runs/2026-01-12-daily/claims.jsonl" in (out / "runs.json").read_text()  # the agent index still lists the issue and its claims


def test_a_home_row_opens_to_its_timestamped_summaries_loaded_from_a_small_fragment(tmp_path):
    """Stated rule (owner, 2026-10-28): clicking a podcast card on the home page expands it to the episode's timestamped summaries.
    The summaries are not in the page (137 KB at the time of writing) but in one small fragment per row, fetched when a row is opened
    or, for the newest day, when the browser is idle. The title stays a link to the episode's page without a script (the script turns it
    into a disclosure button); a row with no summaries, or an influencer's, does not fold."""
    out = build(tmp_path)
    home = (out / "index.html").read_text()
    rows = re.findall(r'<li class="entry[^"]*".*?</li>', home, re.S)
    assert rows and all(r.startswith('<li class="entry fold"') and '<div class="epb" data-src="/episodes/' in r and " hidden></div>" in r
                        and "<details" not in r and re.search(r'<h3><a href="/episodes/[^"]+\.html">', r) for r in rows)
    srcs = re.findall(r'<div class="epb" data-src="([^"]+)" data-page="([^"]+)"', home)
    assert srcs and len({s for s, _ in srcs}) == len(srcs)
    for src, page in srcs:
        frag = (out / site.file_of(src)).read_text()
        assert frag.startswith('<ul class="claims"><li><p>') and 'class="ts"' in frag  # the summaries, each with its timestamp link
        assert f'<a href="{page}">Open the episode page</a>' in frag
        claim = re.search(r"<li><p>(.*?)</p>", frag).group(1)
        assert claim not in home  # the summaries are not inlined
        assert claim in (out / site.file_of(page)).read_text()  # and they are the episode's own page's
    assert 'role="status"' in home and "li.fold" in home and "aria-expanded" in home  # the script and its status line ride with the rows
    assert 'class="entry fold"' not in (out / "social/index.html").read_text()  # only the home page's rows fold
    assert ".claims" not in (out / "sitemap.xml").read_text() and ".claims" not in (out / "llms.txt").read_text()  # the fragments are not pages
    no_claims = site.top_entry({"id": "rss:z", "title": "No summaries", "page": "/episodes/rss_z.html", "claims": [], "date": "2026-01-01",
                                "published": "2026-01-01", "score": 8, "show": "S"}, expand=True)
    influencer = site.top_entry({"id": "rss:y", "title": "Creator video", "page": "/episodes/rss_y.html", "claims": [{"person": "P"}], "date": "2026-01-01",
                                 "published": "2026-01-01", "score": 8, "show": "S", "influencer": True}, expand=True)
    assert "epb" not in influencer and "fold" not in influencer
    assert 'class="entry"' in no_claims and "epb" not in no_claims and '<a href="/episodes/rss_z.html">No summaries</a>' in no_claims


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
    out = build(tmp_path)

    def get(url):
        f = out / site.file_of(url.removeprefix("https://w.test"))
        return (200, f.read_text(), 1, "") if f.is_file() else (404, "", 1, "")

    monkeypatch.setattr(verify, "get", get)
    runs = [r["run"] for r in json.loads((out / "runs.json").read_text())["runs"]]
    assert {"2026-01-05-weekly", "2026-01-07-latent-space", "2026-01-14", "2026-01-09-daily", "2026-01-12-daily"} <= set(runs)
    for run in runs:
        main(["verify", "https://w.test/", "--run", run])  # exits on any problem
    assert 'url=/#d-2026-01-14"' in (out / "runs/2026-01-14/index.html").read_text()
    with pytest.raises(SystemExit):
        main(["verify", "https://w.test/", "--run", "2026-01-13-weekly"])


def test_signals_sits_beside_the_podcast_home_with_at_least_three_picks_and_agent_files(tmp_path):
    """Stated rule (owner, 2026-10-28): the home page stays the podcast home and carries a collapsible Signals panel beside it, /signals/
    shows at least three picks (the weak ones labelled lower confidence), and agents get stable JSON, a schema, llms.txt and a
    Markdown twin. With no Signals data the home has no panel."""
    pub, out = tmp_path / "published", tmp_path / "dist"
    make_published(pub)
    site.build(pub, out)
    assert "<h2>Episodes</h2>" in (out / "index.html").read_text() and (out / "signals/index.html").exists() and "No signals are published yet" in (out / "signals/index.html").read_text() and "signals-panel" not in (out / "index.html").read_text()
    visible_routes = [path for path, _, _ in (*site.NAV_PRIMARY, *site.NAV_MENU, site.NAV_RESEARCH)]
    visible_routes.extend(("/signals/",))
    assert all((out / site.file_of(path)).exists() for path in visible_routes)
    social = (out / "social/index.html").read_text()
    assert "<h1>Social</h1>" in social and "/x/" not in social
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
    assert "<h2>Episodes</h2>" in home and '<details class="signals-panel" id="signals-panel" open>' in home and "All of today" in home
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
