"""Small parsers whose edge cases a command run would not reach: transcript formats and the link an episode gets."""
from sigma.ingest import page_url, parse_duration
from sigma.transcribe import fmt_ts, parse_cues, parse_json, title_match, to_seconds


def test_transcript_formats_timestamps_durations_and_title_matching():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v>Hello there</v>\n\n00:01:05.500 --> 00:01:07.000\nSecond line"
    assert [s["start"] for s in parse_cues(vtt)] == [1.0, 65.5]
    omny = parse_cues("00:00:02\nSpeaker 1: Bloomberg Audio.\n\n00:00:04\nSpeaker 2: Hi.")  # a publisher that labels speakers
    assert omny[0]["speaker"] == "Speaker 1" and omny[1]["text"] == "Hi."
    assert parse_json('{"segments": [{"startTime": 3.5, "body": "Hi", "speaker": "Joe"}]}') == [{"start": 3.5, "speaker": "Joe", "text": "Hi"}]
    assert to_seconds("1:02:03") == 3723 and fmt_ts(3723) == "1:02:03"
    assert parse_duration("1:02:03") == 3723 and parse_duration("45:00") == 2700 and parse_duration("600") == 600
    assert parse_duration(None) is None and parse_duration("abc") is None
    assert title_match("Jensen Huang on AI capex", "Jensen Huang | AI Capex & more") >= 0.6 and title_match("Seinfeld", "Nvidia earnings") == 0


def test_an_episode_links_to_its_own_page_never_to_audio_or_a_tracker():
    audio = "https://traffic.megaphone.fm/PDP1.mp3"
    show = "https://show.example"
    assert page_url({"link": "https://show.example/ep1"}, audio) == "https://show.example/ep1"
    assert page_url({"link": audio}, audio, show) == show  # the item link is the audio file: the show page instead
    assert page_url({"link": "https://prfx.byspotify.com/e/dts.podtrac.com/redirect.mp3/x"}, None, None) == ""
    assert page_url({"links": [{"rel": "alternate", "href": "https://a.example/p"}, {"type": "audio/mpeg", "href": audio}]}, audio) == "https://a.example/p"
    assert page_url({"id": "https://show.example/ep1"}, audio, show) == "https://show.example/ep1"  # no link: a guid that is a page
    assert page_url({"id": audio}, audio, show) == show and page_url({"id": "https://dts.podtrac.com/redirect.mp3/x"}, None, show) == show
    assert page_url({"link": "https://show.example/real", "id": "https://show.example/guid"}, audio, show) == "https://show.example/real"
    entry = {"id": "not a url", "links": [{"rel": "enclosure", "href": audio, "type": "audio/mpeg"},
                                          {"rel": "alternate", "href": "https://show.example/alt"}]}
    assert page_url(entry, audio, show) == "https://show.example/alt"
    assert page_url({**entry, "id": "https://show.example/g"}, audio, show) == "https://show.example/g"
    assert page_url({"id": "urn:uuid:1"}, audio, None) == ""  # nothing usable: empty, never invented
