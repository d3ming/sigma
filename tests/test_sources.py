"""Where episodes are looked up and how a transcript is chosen: source config, fallback order, budget, iTunes person search."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sigma import ingest, transcribe
from sigma import people as pm
from sigma.config import Source, load_sources
from sigma.ingest import Episode, canonical_id
from sigma.people import Person, apply_source_tiers, feed_transcripts, from_itunes, ITUNES_RETRIES, on_topic, parse_itunes
from sigma.whisper import Budget, segments_until

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def ep(**kw):
    return Episode(**{"id": "rss:1", "source_id": "s", "source_name": "S", "tier": 1, "title": "T", "url": "u",
                      "published_at": NOW, **kw})


def test_a_source_falls_back_in_order_and_a_person_hit_inherits_its_shows_tier(monkeypatch, tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("sources:\n  - {id: a, name: A, tier: 1, rss: x, transcripts: [magic]}\n")
    with pytest.raises(ValueError):
        load_sources(p)  # an unknown transcript method is a config error, not a silent skip
    calls = []

    def boom(*a):
        calls.append("rss")
        raise OSError

    monkeypatch.setitem(ingest.FINDERS, "rss", boom)
    monkeypatch.setitem(ingest.FINDERS, "ytdlp", lambda *a: calls.append("ytdlp") or [ep(id="yt:v", youtube_id="v")])
    src = Source("a", "A", 1, rss="x", youtube="https://www.youtube.com/@A/videos", fallback=["ytdlp"], transcripts=["youtube_captions"])
    eps, how = ingest.find(src, NOW, 7)
    assert calls == ["rss", "ytdlp"] and how == "ytdlp" and eps[0].methods == ["youtube_captions"]

    # failure-seen (2026-10-26): libsyn's feeds returned 502 and 20VC came in empty. Apple's copy of the feed is next,
    # and keeps the feed's guid: rss:55e1f0ea0fe53832 is the id the feed gave this Nadella episode that night.
    apple = {"results": [{"wrapperType": "track", "kind": "podcast", "collectionName": "20VC", "collectionId": 958230465,
                          "artworkUrl600": "https://example.invalid/show.jpg"},
                         {"wrapperType": "podcastEpisode", "episodeGuid": "ade69352-b9cb-4e49-a952-a7d7741a3203",
                          "trackName": "20VC: Satya Nadella", "releaseDate": "2026-10-20T07:07:00Z", "trackTimeMillis": 1566000,
                          "episodeUrl": "https://traffic.libsyn.com/n.mp3", "trackViewUrl": "https://podcasts.apple.com/e",
                          "artworkUrl600": "https://example.invalid/episode.jpg"}]}
    monkeypatch.setitem(ingest.FINDERS, "itunes",
                        lambda s, now, days: ingest.from_itunes(s, now, days, get=lambda *a, **k: SimpleNamespace(
                            raise_for_status=lambda: None, json=lambda: apple)))
    calls.clear()
    eps, how = ingest.find(Source("20vc", "20VC", 2, rss="x", itunes_id=958230465, youtube="y", fallback=["itunes", "ytdlp"]), NOW, 7)
    assert calls == ["rss"] and how == "itunes" and [e.id for e in eps] == ["rss:55e1f0ea0fe53832"]
    assert eps[0].audio_url == "https://traffic.libsyn.com/n.mp3"
    assert eps[0].show_image_url == "https://example.invalid/show.jpg" and eps[0].image_url == "https://example.invalid/episode.jpg"
    srcs = [Source(id="tbpn", name="TBPN", tier=1, rss="https://feeds.transistor.fm/technology-brother", itunes_id=1772360235),
            Source(id="t3", name="Ticker Symbol YOU", tier=3, rss="https://x.example/rss"),
            Source(id="iltb", name="Invest Like the Best", tier=1, rss="https://x.example/iltb"),
            Source(id="bg2", name="BG2 Pod", tier=1, rss="https://x.example/bg2")]

    def hit(show, url="", feed=None):
        return Episode(id="x", source_id="person:X", source_name=show, tier=2, title="t", url=url, published_at=NOW, feed_url=feed)

    hits = [hit("Other", feed="http://feeds.transistor.fm/technology-brother/"),
            hit("Renamed", url="https://podcasts.apple.com/us/podcast/x/id1772360235?i=1"), hit("ticker symbol you!"), hit("Unknown Show"),
            hit("Invest Like the Best with Patrick O'Shaughnessy"), hit("BG2Pod with Brad Gerstner and Bill Gurley")]
    out = apply_source_tiers(hits, srcs)  # the last two were stored as tier 2 under Apple's longer names (2026-10-25)
    assert [e.tier for e in out] == [1, 1, 3, 2, 1, 1]  # by feed, by Apple id, by name; unknown stays tier 2
    assert [e.source_name for e in out[4:]] == ["Invest Like the Best", "BG2 Pod"]


def test_transcript_methods_run_in_order_within_the_budget_and_feed_links_are_loaded_once(monkeypatch):
    import sigma.whisper as w

    monkeypatch.setattr(transcribe, "from_rss_tag", lambda links, used=None: None)
    monkeypatch.setattr(w, "transcribe", lambda url, b: (b.spend(600) or [{"start": 0, "speaker": None, "text": "x"}], 600))
    b = Budget(30, 20)
    segs, label = transcribe.get_transcript(ep(transcript_urls=[{"url": "t"}], audio_url="a", methods=["podcast_transcript", "whisper"]), b)
    assert label == "whisper base.en (10 min)" and b.used == 600
    assert transcribe.get_transcript(ep(audio_url="a", methods=["whisper"])) == (None, None)  # whisper needs a budget
    b = Budget(50, 30)
    assert b.take() == 1800
    b.spend(1800)
    assert b.take() == 1200
    segs = [SimpleNamespace(start=s, text=f" {s} ") for s in (0, 100, 200)]
    assert [s["text"] for s in segments_until(segs, 150)] == ["0", "100"]
    entry = {"id": "g1", "podcast_transcript": {"url": "https://x/t.vtt", "type": "text/vtt"}, "links": []}
    calls = []

    def parse(url):
        calls.append(url)
        if url == "https://bad":
            raise OSError("down")
        return SimpleNamespace(entries=[entry])

    eps = [ep(id=canonical_id("g1", None, None), feed_url=u) for u in ("https://feed", "https://feed", "https://bad")]
    other = ep(id="rss:none", feed_url="https://feed")  # same feed, another guid: gets nothing
    assert feed_transcripts([*eps, other], parse=parse) == 2
    assert sorted(calls) == ["https://bad", "https://feed"] and eps[2].transcript_urls is None and other.transcript_urls is None
    assert eps[0].transcript_urls[0]["url"] == "https://x/t.vtt"


def test_person_search_backs_off_on_429_keeps_person_order_and_skips_namesakes(monkeypatch):
    import time

    p, now, slept = Person("Jane Doe", "CEO", "core"), datetime(2026, 10, 23, tzinfo=timezone.utc), []
    r429 = SimpleNamespace(status_code=429, headers={"Retry-After": "3"}, raise_for_status=lambda: (_ for _ in ()).throw(OSError("429")))
    ok = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None, json=lambda: {"results": []})
    seq = [r429, r429, ok]
    assert from_itunes(p, now, 2, get=lambda *a, **k: seq.pop(0), sleep=slept.append) == [] and slept == [3.0, 3.0]
    calls = []
    with pytest.raises(OSError):
        from_itunes(p, now, 2, get=lambda *a, **k: calls.append(1) or r429, sleep=lambda s: None)
    assert len(calls) == ITUNES_RETRIES
    ps = [Person(n, "x", "core") for n in ("A", "B", "C", "D")]

    def fake(person, now_, days):
        time.sleep({"A": 0.03, "B": 0.0}.get(person.name, 0.01))  # finish in the opposite order to the list
        if person.name == "C":
            raise RuntimeError("down")
        titles = {"A": "Zebra economics", "B": "Quantum chips", "D": "Bond auction fallout"}
        return [ep(id=f"rss:{person.name}", title=titles[person.name], source_id=person.tag)]

    monkeypatch.setitem(pm.FINDERS, "itunes", fake)
    kept, info = pm.discover_people(ps, now, 2, [])
    assert [e.id for e in kept] == ["rss:A", "rss:B", "rss:D"] and info["errors"] == ["C/itunes: RuntimeError"]
    es = Person("Eric Schmidt", "former Google CEO", "core", context=["Google", "AI"])
    base = {"releaseDate": "2026-10-22T08:00:00Z", "trackTimeMillis": 3_600_000, "episodeGuid": "g"}
    rows = [{**base, "trackName": "FULL SHOW: Kurtiss Riggs (SDSU vs UND vs USD)", "description": "Eric Schmidt joins",
             "collectionName": "Riggs Radio", "genres": [{"name": "Sports", "id": "1545"}]},
            {**base, "trackName": "Drew Trafton, Sam Herder, Eric Schmidt", "description": "FCS football", "collectionName": "Hero Sports"},
            {**base, "episodeGuid": "g2", "trackName": "Eric Schmidt on AI and China", "description": "Former Google CEO",
             "collectionName": "Tech Show", "genres": [{"name": "Technology"}]}]
    assert [e.title for e in parse_itunes(es, rows, datetime(2026, 10, 22, 12, tzinfo=timezone.utc), 2)] == ["Eric Schmidt on AI and China"]
    assert not on_topic(es, "Eric Schmidt talks gardening", "", "Garden Hour")
    assert on_topic(Person("Jane Doe", "", "watch"), "Jane Doe on chips", "", "Chip Pod")


def test_source_add_says_a_show_is_already_listed_when_its_channel_sits_in_show_links(monkeypatch, tmp_path):
    """failure-seen 2026-10-26: a video from a channel named after the host looked like a new source, but the channel was already Big Technology's."""
    import json
    from sigma import sources as sm

    (tmp_path / "s.yaml").write_text('sources:\n  - {id: bt, name: "Big Technology Podcast", tier: 1, rss: "http://f/bt", topics: [tech]}\n')
    (tmp_path / "l.yaml").write_text("bt:\n  name: Big Technology Podcast\n  youtube: https://www.youtube.com/channel/UCye1YedIypHffYb8k6Gp9wg\n")
    (tmp_path / "e.json").write_text(json.dumps({"topic_names": {"ai": "AI"}}))
    found = {"name": "Alex Kantrowitz", "rss": "", "itunes_id": None, "youtube_channel_id": "UCye1YedIypHffYb8k6Gp9wg"}
    monkeypatch.setattr(sm, "resolve", lambda url: found)
    monkeypatch.setattr(sm, "fill", lambda *a, **k: {})
    args = SimpleNamespace(url="u", sources=tmp_path / "s.yaml", links=tmp_path / "l.yaml", entities=tmp_path / "e.json", tier=2,
                           topics="ai", name=None, id=None, news=False, dry_run=False, style="influencer")
    sm.add_cmd(args)
    assert [s.id for s in load_sources(tmp_path / "s.yaml")[0]] == ["bt"]  # nothing added
    found.update(name="New Show", rss="http://f/new", youtube_channel_id="")
    before = (tmp_path / "s.yaml").read_text()
    with pytest.raises(SystemExit, match="YouTube"):  # stated rule: a Social creator is added from its YouTube channel
        sm.add_cmd(args)
    assert (tmp_path / "s.yaml").read_text() == before
    found.update(youtube_channel_id="UC" + "x" * 22)
    sm.add_cmd(args)
    added = load_sources(tmp_path / "s.yaml")[0][-1]
    assert (added.id, added.tier, added.topics, added.rss, added.style) == ("new-show", 2, ["ai"], "http://f/new", "influencer")  # --style reaches the file
    assert added.youtube == "https://www.youtube.com/channel/UC" + "x" * 22 + "/videos"


def test_an_influencer_source_without_a_youtube_channel_is_refused(tmp_path):
    """Stated rule: every Social creator publishes to YouTube as its primary source."""
    (tmp_path / "s.yaml").write_text('sources:\n  - {id: a, name: A, tier: 2, style: influencer, rss: "http://f/a", topics: []}\n')
    with pytest.raises(ValueError, match="a: .*YouTube"):
        load_sources(tmp_path / "s.yaml")
