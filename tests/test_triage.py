"""Which episodes are worth whispering: sigma.triage on small manifests. The picks are what `sigma transcribe --top N` transcribes."""
import json
from datetime import datetime, timezone

from sigma import triage as tri
from sigma.people import Person
from sigma.triage import named_guests, triage

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
PEOPLE = [Person("Jane Placeholder", "CEO", "core"), Person("Omar Example", "founder", "watch"),
          Person("Chamath Palihapitiya", "x", "core"), Person("Sam Altman", "x", "core")]


def row(i, title, tag="", tier=2, news=False, audio=True, has=False, published="2026-10-22", desc="", dur=None, source=None):
    return {"episode_id": i, "title": title, "source": source or f"Show {i}", "source_tag": tag, "tier": tier, "news": news, "description": desc, "duration": dur,
            "audio_url": f"https://cdn.example/{i}.mp3" if audio else None, "has_transcript": has, "published": published}


def test_the_top_n_plus_core_people_and_never_news_clips_or_off_topic_namesakes():
    is_news = lambda e: e["news"]  # noqa: E731
    m = {"episodes": [row("n1", "Squawk Pod: markets", tier=1, news=True), row("t1", "Founder interview on AI chips", tier=1),
                      row("t2", "Random chat", tier=3), row("t3", "CFO on guidance"),
                      row("core", "Old show", tag="person:Jane Placeholder", tier=3, published="2026-10-10"),
                      row("done", "Already done", has=True), row("w", "Omar Example on rates", tier=3)]}
    ids = triage(m, PEOPLE, top=2, now=NOW, is_news=is_news)
    assert ids == triage(json.loads(json.dumps(m)), PEOPLE, top=2, now=NOW, is_news=is_news)  # the same input picks the same episodes
    assert "core" in ids and len(ids) == 2 + (0 if "core" in ids[:2] else 1)
    e = {x["episode_id"]: x for x in m["episodes"]}
    assert e["n1"]["triage"]["whisper"] is False and "news show" in e["n1"]["triage"]["reasons"]
    assert "rank" not in e["done"]["triage"] and m["triage"]["candidates"] == 6  # an episode with a transcript is not a candidate
    assert "core" in triage(m, PEOPLE, top=1, now=NOW, is_news=is_news)  # a core person is never dropped
    # an executive on a tier-1 show beats a person-search hit that is off topic; a short copy of a longer episode is dropped
    m = {"episodes": [
        row("exec", "Democratizing Security with Cloudflare CTO Dane Knecht", tier=1),
        row("inv", "Stan Druckenmiller: Macro, QE, Inflation"),
        row("psy", "She Psychically Read Sam Altman", tag="person:Sam Altman", desc="a mystic reads souls"),
        row("full", "Chamath: AGI Is Here, Anthropic's Giveaway", tag="person:Chamath Palihapitiya", dur=7300),
        row("clip", "AGI Is Already Here | Chamath Palihapitiya", tag="person:Chamath Palihapitiya", dur=3100),
        row("meh", "Random chat", tier=3)]}
    ids = triage(m, PEOPLE, top=3, now=NOW)
    assert m["triage"]["clips"] == {"clip": "full"}
    assert "clip" not in ids and "psy" not in ids  # neither top-N nor the core override
    assert {"exec", "inv"} <= set(ids)
    a = row("a", "Chamath on AGI", tag="person:Chamath Palihapitiya", dur=3000, source="X")
    b = row("b", "Chamath on AGI and power", tag="person:Chamath Palihapitiya", dur=3200, source="Y")
    assert tri.find_clips([a, b], tri.person_index(PEOPLE)) == {}  # similar length: not a clip


def test_headline_guests_raise_a_title_and_show_names_are_not_guests():
    titles = {"pair": "Arvind Krishna & Nikesh Arora: Quantum Threat, Open vs Frontier AI, AI Cyber Warfare & SaaS Collapse",
              "on": "Sundar Pichai on Gemini 4 and the AI compute crunch", "trail": "Datacenters | Jensen Huang",
              "none": "Weekly Market Recap", "colon": "Weekly Market: Stocks Fall"}
    m = {"episodes": [row(k, t, tier=1) for k, t in titles.items()]}
    triage(m, [], top=3, now=NOW)
    e = {x["episode_id"]: x["triage"] for x in m["episodes"]}
    assert any(r.startswith("two named guests (Arvind Krishna, Nikesh Arora)") for r in e["pair"]["reasons"])
    for k in ("on", "trail"):
        assert "named guest" in e[k]["reasons"], k
    for k in ("none", "colon"):
        assert not any("named guest" in r for r in e[k]["reasons"]), k
    assert e["pair"]["score"] > e["on"]["score"] > e["none"]["score"]  # pair > single guest > no guest
    assert named_guests("Why Rates Fell | Odd Lots") == [] and named_guests("Why Rates Fell | Planet Money") == []
    assert named_guests("Why Rates Fell | Ada Quill") == ["Ada Quill"]  # a real trailing guest still counts...
    assert named_guests("Why Rates Fell | Ada Quill", "Ada Quill Radio") == []  # ...unless it is the show's own name
    assert named_guests("Morgan Stanley & Goldman Sachs: Who Wins the IPO Season") == []
    assert named_guests("Bitcoin Miners and Data Centers: A Merger Wave") == []
    assert named_guests("Arvind Krishna & Nikesh Arora: Quantum Threat") == ["Arvind Krishna", "Nikesh Arora"]
