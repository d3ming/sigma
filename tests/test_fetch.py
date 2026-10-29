"""`sigma fetch`, `sigma merge` and `sigma transcribe`: feeds in, a run folder out. Feeds, transcript files, yt-dlp and Whisper are fakes."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import pytest
import requests

from sigma import feedcache, fetch as fetch_mod, transcribe, whisper
from sigma.cli import main
from sigma.store import Store
from tests.helpers import LONG, ep, make_run, targs

NOW = datetime.now(timezone.utc)
SOURCES = """t3_weekly_cap: 2
sources:
  - {id: widget, name: Widget Show, tier: 1, rss: 'https://feed.invalid/w', transcripts: [podcast_transcript]}
  - {id: gadget, name: Gadget Hour, tier: 1, rss: 'https://feed.invalid/g', transcripts: [podcast_transcript]}
  - {id: lowa, name: Low A, tier: 3, rss: 'https://feed.invalid/la', transcripts: [podcast_transcript]}
  - {id: lowb, name: Low B, tier: 3, rss: 'https://feed.invalid/lb', transcripts: [podcast_transcript]}
"""


def item(guid, title, days_ago, vtt=None):
    when = format_datetime(NOW - timedelta(days=days_ago, hours=1))
    tag = f'<podcast:transcript url="https://t.invalid/{vtt}.vtt" type="text/vtt"/>' if vtt else ""
    return (f"<item><guid>{guid}</guid><title>{title}</title><link>https://show.invalid/{guid}</link><pubDate>{when}</pubDate>"
            f'<enclosure url="https://cdn.invalid/{guid}.mp3" type="audio/mpeg" length="1"/>{tag}</item>')


def feed(*items):
    return ('<?xml version="1.0"?><rss xmlns:podcast="https://podcastindex.org/namespace/1.0" version="2.0"><channel>'
            f"<link>https://show.invalid</link>{''.join(items)}</channel></rss>").encode()


def vtt(cues):
    return "WEBVTT\n\n" + "".join(f"00:{i // 2:02d}:{i % 2 * 30:02d}.000 --> 00:{i // 2:02d}:{i % 2 * 30 + 29:02d}.000\n{'spoken words ' * 40}\n\n"
                                  for i in range(cues))


PAGES = {
    "https://feed.invalid/w": feed(item("w1", "Founders on chips", 1, "long"), item("w2", "Short notes", 2, "short"),
                                   item("w3", "Replay: Founders best of 2025", 3), item("w4", "Fourth recent", 4),
                                   item("w5", "Fifth recent", 5), item("w6", "Last month", 40)),
    "https://feed.invalid/g": requests.ConnectionError("feed host is down"),
    "https://feed.invalid/la": feed(item("la1", "Low A one", 1), item("la2", "Low A two", 2)),
    "https://feed.invalid/lb": feed(item("lb1", "Low B one", 1)),
    "https://t.invalid/long.vtt": vtt(31),  # 18,600 characters: a transcript
    "https://t.invalid/short.vtt": vtt(4),  # 1,920 characters: a show description
}


@pytest.fixture
def web(monkeypatch):
    """requests.get answers from PAGES (an Exception value is raised); feedparser runs in-process."""
    seen = []

    def get(url, headers=None, timeout=None, **kw):
        seen.append(url)
        page = PAGES[url]
        if isinstance(page, Exception):
            raise page
        body = page.encode() if isinstance(page, str) else page
        return SimpleNamespace(status_code=200, content=body, text=body.decode(), headers={}, url=url, ok=True, raise_for_status=lambda: None)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(feedcache, "pool_parse", feedcache.parse_bytes)
    return seen


def fetch(tmp_path, name, *extra):
    (tmp_path / "sources.yaml").write_text(SOURCES)
    main(["fetch", "--sources", str(tmp_path / "sources.yaml"), "--runs", str(tmp_path / "runs"), "--run-name", name, "--people", "",
          "--db", str(tmp_path / "db.sqlite"), "--days", "7", "--per-source", "3", *extra])
    run = tmp_path / "runs" / name
    return run, json.loads((run / "manifest.json").read_text())


def test_fetch_keeps_what_the_rules_keep_and_remembers_it(tmp_path, web, capsys):
    run, m = fetch(tmp_path, "day1")
    titles = {e["title"]: e for e in m["episodes"]}
    # window 7 days, 3 per show, tier-3 shows share a cap of 2 (t3_weekly_cap), a replay is set aside, a dead feed is recorded
    assert sorted(titles) == ["Founders on chips", "Low A one", "Low A two", "Short notes"]
    assert [x["title"] for x in m["excluded"]] == ["Replay: Founders best of 2025"] and m["excluded"][0]["why"] == "rerun"
    w = m["sources"]["widget"]  # w6 is outside the window; the two over the per-source cap are named, not lost
    assert (w["via"], w["found"], w["kept"], w["error"], len(w["capped"])) == ("rss", 5, 3, None, 2) and {"title", "published"} == set(w["capped"][0])
    assert m["sources"]["lowb"]["found"] == 1 and m["sources"]["lowb"]["kept"] == 0 and len(m["sources"]["lowb"]["capped"]) == 1
    assert "capped" not in m["sources"]["lowa"] or m["sources"]["lowa"]["found"] > m["sources"]["lowa"]["kept"]
    assert "feed host is down" in m["sources"]["gadget"]["error"] and m["sources"]["gadget"]["kept"] == 0
    # the feed's transcript link was followed; a text under 5,000 characters is a show description, not a transcript
    good, short = titles["Founders on chips"], titles["Short notes"]
    assert good["has_transcript"] and good["transcript_source"] == "podcast:transcript" and good["transcript_minutes"] == 15
    assert good["transcript_url"] == "https://t.invalid/long.vtt" and good["audio_url"] == "https://cdn.invalid/w1.mp3"
    assert short["fallback_text"] and not short["has_transcript"] and short["transcript_source"] == "fallback"
    assert not titles["Low A one"]["has_transcript"] and titles["Low A one"]["transcript_source"] is None
    md = (run / good["file"]).read_text()
    assert md.startswith("---\nepisode_id: " + good["episode_id"] + "\n") and "transcript_source: podcast:transcript" in md
    assert "[0:00:30] spoken words" in md and "_No transcript found._" in (run / titles["Low A one"]["file"]).read_text()
    assert m["timing"]["fetch"]["end"] and not (run / "transcribe.lock").exists()
    # the same command again adds nothing; on another day the episodes already seen are skipped, not fetched twice
    capsys.readouterr()
    _, again = fetch(tmp_path, "day1")
    assert len(again["episodes"]) == 4 and "adding only new ones" in capsys.readouterr().out
    _, next_day = fetch(tmp_path, "day2")
    assert not next_day["episodes"] and len(next_day["skipped_seen"]) == 4
    assert next_day["excluded"][0]["why"] == "rerun"
    _, refetched = fetch(tmp_path, "day3", "--refetch", "--include-reruns")
    assert len(refetched["episodes"]) == 5 and not refetched["excluded"]


def test_a_failing_transcript_lookup_keeps_the_episode_and_is_retried_next_time(tmp_path, web, monkeypatch, capsys):
    """One episode's lookup (timeout, yt-dlp missing, blocked IP) never aborts the fetch; it is not recorded as done."""
    def hang(*a, **k):
        raise subprocess.TimeoutExpired("yt-dlp", 120)

    real_run = subprocess.run
    monkeypatch.setattr(subprocess, "run", hang)
    monkeypatch.setattr(transcribe, "YT_BLOCKED", transcribe.threading.Event())
    run, m = fetch(tmp_path, "day1", "--only", "lowa", "--youtube-mirror")
    assert [e["title"] for e in m["episodes"]] == ["Low A one", "Low A two"] and "TimeoutExpired" in capsys.readouterr().out
    assert not m["skipped_seen"] and not Store(tmp_path / "db.sqlite").db.execute("SELECT 1 FROM episodes").fetchall()
    monkeypatch.setattr(subprocess, "run", real_run)
    _, retry = fetch(tmp_path, "day2", "--only", "lowa")
    assert len(retry["episodes"]) == 2 and not retry["skipped_seen"]  # the failed lookups were not remembered, so day 2 tries again


def test_youtube_mirror_rules(monkeypatch):
    t = "Why the AI Trade Cracked and What Anthropic Filed"
    run = lambda *lines: monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout="\n".join(lines)))
    run(f"clip1111111\t{t}\tAll-In Clips", f"show1111111\t{t}\tAll-In Podcast")
    assert transcribe.find_youtube_mirror("All-In Podcast", t) == "show1111111"  # the show's channel, not the clips one listed first
    run(f"clip1111111\t{t}\tAll-In Clips")
    assert transcribe.find_youtube_mirror("All-In Podcast", t) is None
    run(f"short111111\t{t} #shorts\tAll-In Podcast")
    assert transcribe.find_youtube_mirror("All-In Podcast", t) is None
    run("loose111111\tAI trade cracked while Anthropic filed an S-1 and more\tSome Label")
    assert transcribe.find_youtube_mirror("All-In Podcast", t) is None  # a loose title on an unrelated channel
    run(f"real1111111\t{t}\tBloomberg Podcasts")
    assert transcribe.find_youtube_mirror("Odd Lots", t) == "real1111111"  # a network channel with the exact title


def test_a_youtube_block_stops_further_lookups(monkeypatch):
    import sys
    import types

    calls = []

    class IpBlocked(Exception):
        pass

    class Api:
        def fetch(self, vid, languages):
            calls.append(vid)
            raise IpBlocked()

    monkeypatch.setitem(sys.modules, "youtube_transcript_api", types.SimpleNamespace(YouTubeTranscriptApi=Api))
    monkeypatch.setattr(transcribe, "YT_BLOCKED", transcribe.threading.Event())
    assert transcribe.from_youtube("aaaaaaaaaaa") is None and transcribe.from_youtube("bbbbbbbbbbb") is None
    assert calls == ["aaaaaaaaaaa"]  # one request, no retries, nothing after the block
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no search while blocked")))
    assert transcribe.find_youtube_mirror("Show", "Title") is None


SEGS = [{"start": 0.0, "speaker": None, "text": "hi " + "a" * 3000}, {"start": 600.0, "speaker": None, "text": "bye " + "b" * 3000}]


def rows(run):
    return {e["episode_id"]: e for e in json.loads((run / "manifest.json").read_text())["episodes"]}


def test_transcribe_is_resumable_prefetches_and_records_failures(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    eps = [ep("rss:a", "A one", "odd-lots"), ep("rss:b", "B two", "odd-lots"), ep("rss:c", "C three", "odd-lots")]
    eps[2].audio_url, eps[2].youtube_id = None, "ccc"  # YouTube-only
    eps.append(ep("rss:d", "D four", "odd-lots"))
    rows_ = [fetch_mod.write_episode(run, e, None, None) for e in eps[:3]]
    # d came with 300 characters of "transcript" that an earlier fetch (--min-transcript-chars 100) accepted; the 5,000 rule says it is a description
    rows_.append(fetch_mod.write_episode(run, eps[3], [{"start": 0.0, "speaker": None, "text": "x" * 300}], "podcast:transcript", min_chars=100))
    assert rows_[3]["has_transcript"]
    (run / "manifest.json").write_text(json.dumps({"episodes": rows_}))
    db = tmp_path / "db.sqlite"
    for e in eps:
        Store(db).add_episode(e, None)
    calls, files = [], []
    monkeypatch.setattr(whisper, "PREFETCH", True)  # download the next episode while the current one transcribes
    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(whisper, "transcribe_youtube", lambda vid, budget: calls.append("youtube") or (budget.spend(60) or SEGS, 60.0))

    def download(url, f, **kw):
        calls.append(url)
        if url.endswith("rss:b.mp3"):
            raise whisper.DownloadError("HTTPError 404", 1, ["HTTPError 404"], False)
        f.write(b"x")

    def transcribe_file(path, budget):
        files.append(path)
        budget.spend(120)
        return SEGS, 120.0

    monkeypatch.setattr(whisper, "download", download)
    monkeypatch.setattr(whisper, "transcribe_file", transcribe_file)
    fetch_mod.transcribe_run(targs(run, top=0, people=None, db=str(db)))
    man = json.loads((run / "manifest.json").read_text())
    a, b, c, d = man["episodes"]
    assert a["has_transcript"] and a["transcript_source"] == "whisper base.en (2 min)" and c["has_transcript"]
    assert d["has_transcript"] and d["transcript_source"] == "whisper base.en (2 min)" and d["fallback_from"] == "podcast:transcript"
    assert b["whisper_error"] == "HTTPError 404" and not b["has_transcript"]
    assert [f["episode_id"] for f in man["failures"]] == ["rss:b"] and man["failures"][0]["transient"] is False
    assert "rss:b" in (run / "transcribe.failed.log").read_text() and man["whisper_minutes"] == 5.0
    assert not (run / "transcribe.lock").exists() and not any(os.path.exists(f) for f in files)  # downloaded audio is removed
    text = (run / a["file"]).read_text()
    assert "transcript_source: whisper base.en (2 min)" in text and "[0:10:00] bye b" in text and "_No transcript" not in text
    assert Store(db).db.execute("SELECT transcript_source FROM episodes WHERE id='rss:a'").fetchone()[0] == "whisper base.en (2 min)"
    calls.clear()
    fetch_mod.transcribe_run(targs(run, top=0, people=None))
    assert calls == []  # the rerun retries nothing that finished or failed


def test_triage_whispers_the_top_pick_and_every_other_tier_1_episode_unless_told_not_to(monkeypatch, tmp_path):
    from dataclasses import replace

    def week(name):
        eps = [ep("rss:a", "Top pick CEO interview on AI chips"), ep("rss:b", "Plain chat"), ep("rss:n", "Market wrap"), ep("rss:r", "Replay"),
               replace(ep("rss:t2", "Other chat"), tier=2), replace(ep("rss:t3", "Another chat"), tier=3)]
        return make_run(tmp_path / name / "r", eps, **{"rss:n": {"news": True}, "rss:r": {"rerun": True}})

    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(fetch_mod, "is_news", lambda e: e.get("news", False))
    calls = []
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: calls.append(url.split("/")[-1]) or (LONG, 60.0))
    fetch_mod.transcribe_run(targs(week("floor"), top=1, people=None))
    assert sorted(calls) == ["rss:a.mp3", "rss:b.mp3"]  # the top pick, plus the tier-1 floor; not news, a replay or lower tiers
    calls.clear()
    fetch_mod.transcribe_run(targs(week("nofloor"), top=1, people=None, no_tier1_floor=True))
    assert calls == ["rss:a.mp3"]  # --top 1 means one
    calls.clear()  # three tier-2 episodes and --top 2: the third is not whispered, and the manifest says what triage decided
    run = make_run(tmp_path / "t2" / "r", [replace(ep(f"rss:{c}", t), tier=2) for c, t in
                                           (("a", "Founder interview on AI chips"), ("b", "Random chat"), ("c", "CEO on guidance"))])
    fetch_mod.transcribe_run(targs(run, top=2, people=None))
    assert len(calls) == 2 and "rss:b.mp3" not in calls
    assert json.loads((run / "manifest.json").read_text())["triage"] == {"top": 2, "tier1_floor": True, "candidates": 3, "whisper": 2, "clips": {}}


def test_fetch_merge_and_transcribe_wait_for_the_manifest_lock_and_still_land_their_edits(tmp_path, web, monkeypatch):
    """AGENTS.md: manifest.json is written only through sigma.manifest.update, because transcribe runs for hours while other
    commands edit the same file. With the lock held, each command waits; once it is free the command's edit is in the file."""
    import fcntl
    import threading

    run, first = fetch(tmp_path, "day1", "--only", "widget")
    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: (b.spend(60) or SEGS, 60.0))
    commands = {"fetch": (lambda: fetch(tmp_path, "day1", "--only", "lowa"), lambda m: any(e["title"] == "Low A one" for e in m["episodes"])),
                "transcribe": (lambda: fetch_mod.transcribe_run(targs(run, top=0, people=None)),
                               lambda m: m["timing"]["transcribe"]["end"])}
    for name, (command, landed) in commands.items():
        before = (run / "manifest.json").read_text()
        with open(run / "manifest.json.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            t = threading.Thread(target=command)
            t.start()
            t.join(0.05)
            assert t.is_alive() and (run / "manifest.json").read_text() == before, name
            fcntl.flock(lock, fcntl.LOCK_UN)
        t.join(5)
        assert not t.is_alive() and landed(json.loads((run / "manifest.json").read_text())), name


def test_fetch_duplicate_identity_preserves_episode_numbers_and_transcript_filenames(tmp_path):
    from sigma.ranked import RankedError, validate

    first = ep("rss:21", "Episode 21: The AI infrastructure outlook", "show")
    next_episode = ep("rss:22", "Episode 22: The AI infrastructure outlook", "show")
    known = SimpleNamespace(id=first.id, title=first.title, source_id=first.source_id, url=first.url,
                            published_at=first.published_at.isoformat())
    assert not fetch_mod.same_episode(next_episode, known)
    assert fetch_mod.same_episode(first, known)
    datetime_copy = ep("rss:copy", first.title, "show")
    datetime_copy.url = ""
    assert fetch_mod.same_episode(datetime_copy, first)
    year_left = ep("rss:year-left", "2026 AI Outlook", "show-left")
    year_right = ep("rss:year-right", "2026 AI Outlook", "show-right")
    year_left.url, year_right.url = "https://example.invalid/left", "https://example.invalid/right"
    assert not fetch_mod.same_episode(year_right, year_left)

    shared = "An exceptionally long shared episode title that extends past the filename limit and ends in "
    long_a = ep("rss:long-a", shared + "twenty one", "show")
    long_b = ep("rss:long-b", shared + "twenty two", "show")
    run = tmp_path / "run"
    run.mkdir()
    row_a = fetch_mod.write_episode(run, long_a, None, None)
    row_b = fetch_mod.write_episode(run, long_b, None, None)
    assert row_a["file"] != row_b["file"]
    assert (run / row_a["file"]).exists() and (run / row_b["file"]).exists()

    influencer = {"week_of": "2026-10-22", "run_dir": "runs/daily", "ranked_by": "reader", "episodes": [
        {"rank": 1, "episode_id": "rss:creator", "title": "Creator video", "url": "https://example.invalid/video",
         "source": "Creator", "tier": 3, "published": "2026-10-22", "score": 9, "reason": "Relevant", "claims": []}
    ]}
    validate(influencer, ranking=False)
    with pytest.raises(RankedError, match="tier 3 can never be a top pick"):
        validate(influencer)
