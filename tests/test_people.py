from datetime import datetime, timedelta, timezone

import pytest

from sigma.ingest import Episode, canonical_id
from sigma.people import Person, dedupe, is_clip, load_people, mentions, parse_itunes, youtube_candidates
from sigma.store import Store

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
JH = Person("Jensen Huang", "NVIDIA CEO", "core")
CC = Person("C.C. Wei", "TSMC CEO", "core", ["CC Wei"])


def ep(id, title, src="person:Jensen Huang"):
    return Episode(id=id, source_id=src, source_name="S", tier=2, title=title, url="u", published_at=NOW)


def test_the_watchlist_loads_a_person_and_rejects_bad_priorities_and_duplicates(tmp_path):
    """Stated rule: a person has a supported priority and appears only once; follow lists stay private."""
    p = tmp_path / "p.yaml"
    p.write_text("people:\n  - {name: A, role: r, priority: core}\n")
    assert [(person.name, person.role, person.priority) for person in load_people(p)] == [("A", "r", "core")]
    p.write_text("people:\n  - {name: A, role: r, priority: hot}\n")
    with pytest.raises(ValueError):
        load_people(p)
    p.write_text("people:\n  - {name: A, role: r, priority: core}\n  - {name: A, role: r, priority: watch}\n")
    with pytest.raises(ValueError):
        load_people(p)


def test_which_search_hits_are_about_the_person_and_not_clips():
    assert mentions(CC, "An hour with CC Wei") and mentions(CC, "", "TSMC's C.C. Wei on capacity")  # aliases count
    assert not mentions(JH, "Jensen Huangs") and mentions(JH, "JENSEN HUANG | full interview")  # whole words, any case
    for title, channel, desc, dur, clip in [("Jensen Huang interview", "BG2", "", 3600, False),
                                            ("Jensen Huang interview", "BG2", "", 120, True),  # two minutes
                                            ("Jensen on China | Lex Fridman", "Lex Clips", "", 1800, True),
                                            ("Jensen Huang talk", "X", "Full video: https://youtu.be/x", 1800, True)]:
        assert is_clip(title, channel, desc, dur, 20) is clip, (title, channel, dur)
    rows = [{"id": "a", "title": "Jensen Huang interview", "duration": 3000}, {"id": "b", "title": "Lisa Su interview", "duration": 3000},
            {"id": "c", "title": "Jensen Huang #shorts", "duration": 3000}]
    assert [r["id"] for r in youtube_candidates(JH, 20, rows)] == ["a"]


def test_itunes_hits_and_the_same_episode_found_twice(tmp_path, monkeypatch):
    """Outside-value: Apple search separates podcastEpisode artwork from matching track/kind=podcast collection artwork."""
    rows = [{"trackName": "Jensen Huang on AI", "collectionName": "Show", "releaseDate": "2026-10-19T08:00:00Z",
             "episodeGuid": "g1", "trackTimeMillis": 3_000_000, "episodeUrl": "https://a.mp3", "trackViewUrl": "https://ap",
             "collectionId": 42, "artworkUrl600": "https://example.invalid/episode.jpg"},
            {"trackName": "Jensen Huang old", "releaseDate": "2026-09-01T08:00:00Z", "episodeGuid": "g2", "trackTimeMillis": 3_000_000},
            {"trackName": "Jensen Huang short", "releaseDate": "2026-10-19T08:00:00Z", "episodeGuid": "g3", "trackTimeMillis": 60_000},
            {"trackName": "Other guest", "releaseDate": "2026-10-19T08:00:00Z", "episodeGuid": "g4", "trackTimeMillis": 3_000_000}]
    out = parse_itunes(JH, rows, NOW, 7)
    assert len(out) == 1
    e = out[0]
    assert e.source_id == "person:Jensen Huang" and e.source_name == "Show" and e.audio_url == "https://a.mp3"
    assert e.id == canonical_id("g1", None, None)  # same id as the channel's RSS copy, so dedupe can match it
    assert e.image_url == "https://example.invalid/episode.jpg" and e.show_image_url is None
    collection = {"wrapperType": "track", "kind": "podcast", "collectionId": 42,
                  "artworkUrl600": "https://example.invalid/show.jpg"}
    assert parse_itunes(JH, [collection, *rows], NOW, 7)[0].show_image_url == "https://example.invalid/show.jpg"
    from types import SimpleNamespace
    from sigma.people import from_itunes

    def apple(url, **kwargs):
        if url == "https://itunes.apple.com/search":
            payload = rows
        else:
            assert url == "https://itunes.apple.com/lookup?id=42"
            payload = [collection]
        return SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None,
                               json=lambda: {"results": payload})
    found = from_itunes(JH, NOW, 7, get=apple)
    assert (found[0].image_url, found[0].show_image_url) == ("https://example.invalid/episode.jpg", "https://example.invalid/show.jpg")
    def search_only(url, **kwargs):
        assert url == "https://itunes.apple.com/search"
        return apple(url, **kwargs)
    assert from_itunes(JH, NOW, 7, get=search_only) == found
    monkeypatch.setenv("SIGMA_FEED_CACHE", str(tmp_path / "wrong-collection"))
    collection["collectionId"] = 43
    assert from_itunes(JH, NOW, 7, get=apple)[0].show_image_url is None
    collection["collectionId"] = 42
    channel = [ep("rss:1", "Jensen Huang | Does AI Revenue Justify Capex", "bg2")]
    people = [ep("rss:1", "x"),
              ep("yt:2", "Jensen Huang | Does AI Revenue Justify Capex"),
              ep("yt:3", "Huang and Su on stage at the summit"),
              ep("yt:3", "Huang and Su on stage at the summit", "person:Lisa Su"),
              ep("yt:4", "Huang and Su on stage at the summit (full)", "person:Lisa Su")]
    kept = dedupe(channel, people)
    assert [e.id for e in kept] == ["yt:3"]
    assert kept[0].source_id == "person:Jensen Huang,person:Lisa Su"
    s = Store(tmp_path / "db.sqlite")  # what the channel dedupe compares against never includes people hits
    s.add_episode(ep("yt:a", "Channel ep", "bg2"), None)
    s.add_episode(ep("rss:b", "Person ep"), None)
    assert [k.id for k in s.known_since(NOW - timedelta(days=1))] == ["yt:a"]
