import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from wire import custom, fetch as fetch_mod, people, status, whisper
from wire.cli import main
from wire.ingest import Episode
from tests.helpers import LONG, STATUS_SHAPE, make_run, targs

NOW = datetime.now(timezone.utc)
DAY = 86400


def when(days_ago, hour=8):
    return datetime.fromtimestamp(NOW.timestamp() - days_ago * DAY, timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)


def itunes_ep(i="rss:friar", title="Sarah Friar on OpenAI's models", show="Show A", days_ago=5, **kw):
    return Episode(id=i, source_id="person:Sarah Friar", source_name=show, tier=2, title=title, url=f"https://apple/{i}",
                   published_at=when(days_ago), audio_url=f"https://cdn/{i}.mp3", feed_url="https://feed/a", duration=3600,
                   description="CFO of OpenAI", **kw)


def yt_ep(i="yt:abc", title="Sarah Friar on OpenAI's models", show="Show A TV", days_ago=5, **kw):
    return Episode(id=i, source_id="person:Sarah Friar", source_name=show, tier=2, title=title, url=f"https://youtube.com/watch?v={i[3:]}",
                   published_at=when(days_ago, 12), youtube_id=i[3:], duration=3500, description="video", **kw)


def fake_finders(monkeypatch, itunes=(), youtube=(), query_itunes=(), query_youtube=()):
    monkeypatch.setattr(people, "from_itunes", lambda p, now, days, **kw: list(itunes))
    monkeypatch.setattr(people, "from_youtube_search", lambda p, now, days, **kw: list(youtube))
    monkeypatch.setattr(people, "from_itunes_query", lambda q, now, days, **kw: list(query_itunes))
    monkeypatch.setattr(people, "from_youtube_query", lambda q, now, days, **kw: list(query_youtube))


def run_find(capsys, *argv, runs):
    capsys.readouterr()
    main(["find", "--people", "", "--runs", str(runs), "--json", *argv])
    return json.loads(capsys.readouterr().out)


def test_find_candidates_for_a_person(monkeypatch, capsys, tmp_path):
    """`wire find`: one row per episode however many places carry it, newest first, with where it can be fetched from."""
    other = yt_ep("yt:other", "A different Friar talk", days_ago=3)
    fake_finders(monkeypatch, itunes=[itunes_ep()], youtube=[yt_ep(), other])
    cands = run_find(capsys, "--person", "Sarah Friar", "--role", "OpenAI CFO", runs=tmp_path)
    assert [c["episode_id"] for c in cands] == ["yt:other", "rss:friar"]  # newest first; the YouTube copy folded in
    friar = cands[1]
    assert friar["via"] == ["itunes", "youtube"] and friar["youtube_id"] == "abc" and friar["audio_url"] == "https://cdn/rss:friar.mp3"
    assert friar["people"] == ["Sarah Friar"] and friar["role"] == "OpenAI CFO" and friar["minutes"] == 60 and friar["transcribed"] is None
    # the same title on far-apart dates is two episodes
    fake_finders(monkeypatch, itunes=[itunes_ep(days_ago=20)], youtube=[yt_ep(days_ago=5)])
    assert len(run_find(capsys, "--person", "Sarah Friar", runs=tmp_path)) == 2
    # a person hit and a query hit on the same episode merge; --no-youtube never asks YouTube
    q = Episode(**{**itunes_ep().__dict__, "source_id": "query:openai"})
    fake_finders(monkeypatch, itunes=[itunes_ep()], query_itunes=[q], youtube=[yt_ep("yt:boom")], query_youtube=[yt_ep("yt:boom2")])
    cands = run_find(capsys, "--person", "Sarah Friar", "--query", "openai", "--no-youtube", runs=tmp_path)
    assert len(cands) == 1 and cands[0]["people"] == ["Sarah Friar"] and cands[0]["queries"] == ["openai"] and cands[0]["via"] == ["itunes"]
    # a blocked YouTube search costs only the YouTube hits
    fake_finders(monkeypatch, itunes=[itunes_ep()])

    def boom(*a, **k):
        raise TimeoutError("yt-dlp hung")

    monkeypatch.setattr(people, "from_youtube_search", boom)
    assert [c["episode_id"] for c in run_find(capsys, "--person", "Sarah Friar", runs=tmp_path)] == ["rss:friar"]
    # an episode already transcribed in a run says which
    runs = tmp_path / "runs"
    make_run(runs / "2026-10-17-weekly", [itunes_ep()], segs=LONG)
    fake_finders(monkeypatch, itunes=[itunes_ep(), itunes_ep("rss:new", "Other talk with Friar", days_ago=2)])
    cands = {c["episode_id"]: c for c in run_find(capsys, "--person", "Sarah Friar", runs=runs)}
    assert cands["rss:friar"]["transcribed"]["run"] == "2026-10-17-weekly" and cands["rss:new"]["transcribed"] is None
    # names and roles come from people.yaml, aliases included
    seen = []
    monkeypatch.setattr(people, "from_itunes", lambda p, now, days, **kw: seen.append(p) or [])
    (tmp_path / "p.yaml").write_text("people:\n  - {name: C.C. Wei, role: TSMC CEO, priority: core, aliases: [CC Wei]}\n")
    main(["find", "--people", str(tmp_path / "p.yaml"), "--runs", str(tmp_path), "--person", "c.c. wei", "--context", "TSMC"])
    assert seen[0].aliases == ["CC Wei"] and seen[0].role == "TSMC CEO" and seen[0].context == ["TSMC"]


def test_itunes_query_needs_every_word_a_long_episode_and_the_window():
    def row(title, days_ago, ms=3_600_000, show="Show", genre="Business"):
        return {"trackName": title, "description": "", "collectionName": show, "releaseDate": when(days_ago).isoformat(),
                "trackTimeMillis": ms, "episodeGuid": title, "episodeUrl": f"https://cdn/{title}.mp3", "primaryGenreName": genre}

    rows = [row("OpenAI CFO talks compute", 3), row("OpenAI short", 3, ms=60_000), row("OpenAI old news", 90),
            row("Anthropic only", 3), row("OpenAI football special", 3, genre="Sports"), row("The CFO of OpenAI", 4)]
    resp = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None, json=lambda: {"results": rows})
    got = people.from_itunes_query("OpenAI CFO", NOW, 30, get=lambda *a, **k: resp)
    assert sorted(e.title for e in got) == ["OpenAI CFO talks compute", "The CFO of OpenAI"]
    assert got[0].source_id == "query:OpenAI CFO" and got[0].audio_url.startswith("https://cdn/")


def pick(**kw):
    c = custom.candidate(itunes_ep(), "itunes", people.Person("Sarah Friar", "OpenAI CFO", "watch"))
    return {**c, **kw}


def write_picks(tmp_path, picks, name="picks.json"):
    p = tmp_path / name
    p.write_text(json.dumps(picks))
    return str(p)


def custom_run(tmp_path, picks, name="2026-10-25-openai", *extra):
    main(["custom-run", name, "--picks", write_picks(tmp_path, picks), "--runs", str(tmp_path / "runs"), "--sources", "", *extra])
    return tmp_path / "runs" / name


def manifest(run):
    return json.loads((run / "manifest.json").read_text())


def test_custom_run_from_picks(tmp_path):
    a, b = pick(), pick(episode_id="yt:xyz", title="Altman, staying human", show="Chan", audio_url=None, youtube_id="xyz",
                        people=["Sam Altman"], via=["youtube"])
    run = custom_run(tmp_path, [a], "r", "--note", "OpenAI executives")
    m = manifest(run)
    assert m["kind"] == "custom" and m["note"] == "OpenAI executives" and m["days"] >= 5 and len(m["episodes"]) == 1
    row = m["episodes"][0]
    assert row["episode_id"] == "rss:friar" and row["has_transcript"] is False and row["audio_url"] == "https://cdn/rss:friar.mp3"
    assert row["rerun"] is False and row["matched"] == ["Sarah Friar"] and row["source_tag"] == "person:Sarah Friar"
    md = (run / row["file"]).read_text()
    assert "episode_id: rss:friar" in md and "# Sarah Friar on OpenAI's models" in md and "_No transcript found._" in md
    custom_run(tmp_path, [a, b], "r")  # rerun with one more pick: the first is not duplicated
    m = manifest(run)
    assert [e["episode_id"] for e in m["episodes"]] == ["rss:friar", "yt:xyz"] and m["note"] == "OpenAI executives"
    assert m["episodes"][1]["youtube_id"] == "xyz" and len(m["custom"]) == 2 and m["custom"][1]["added"] == 1
    assert len(list(run.glob("*.md"))) == 2
    custom_run(tmp_path, [pick(episode_id="yt:copy", audio_url=None, youtube_id="copy")], "r")  # same title, same day: already there
    assert len(manifest(run)["episodes"]) == 2
    # a pick already transcribed in another run reuses that transcript instead of being whispered again
    other = make_run(tmp_path / "runs" / "2026-10-17-weekly", [itunes_ep()], segs=LONG)
    row = manifest(custom_run(tmp_path, [pick()], "reuse"))["episodes"][0]
    assert row["has_transcript"] is True and row["transcript_source"] == "whisper (3 min)" and row["reused_from"].startswith(other.name)
    assert "[0:03:10] " + "word " * 100 in (tmp_path / "runs" / "reuse" / row["file"]).read_text()
    # a pick with nothing to fetch, or a name that is another kind of run, is refused
    with pytest.raises(SystemExit, match="neither audio_url nor youtube_id"):
        custom_run(tmp_path, [pick(audio_url=None, youtube_id=None)])
    (tmp_path / "runs" / "daily").mkdir(parents=True)
    (tmp_path / "runs" / "daily" / "manifest.json").write_text(json.dumps({"episodes": []}))
    with pytest.raises(SystemExit, match="not a custom run"):
        custom_run(tmp_path, [pick()], "daily")


def test_transcribe_a_custom_run_and_follow_it_with_status(monkeypatch, tmp_path):
    """A custom run whispers every pick (no triage), YouTube-only picks from the video's audio; a failed download is recorded."""
    run = custom_run(tmp_path, [pick(episode_id="yt:xyz", audio_url=None, youtube_id="xyz", title="Altman, staying human"),
                                pick(title="Replay: Friar best of 2026")])
    d = status.inspect_run(run)
    STATUS_SHAPE.validate(d)
    assert d["kind"] == "custom" and d["stage"] == "transcribe" and d["next"]["type"] == "command"
    assert d["transcribe"]["whisper_pending"] == 2 and "transcribe" in d["next"]["command"] and list(d["stages"]) == ["fetch", "transcribe"]
    calls = []
    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(whisper, "transcribe_youtube", lambda vid, budget: calls.append(vid) or (budget.spend(180) or LONG, 180.0))
    monkeypatch.setattr(whisper, "transcribe", lambda url, budget: calls.append(url) or (budget.spend(180) or LONG, 180.0))
    fetch_mod.transcribe_run(targs(run, top=8, people=None))  # top=8 would triage a daily run; a custom run takes every pick
    rows = {e["episode_id"]: e for e in manifest(run)["episodes"]}
    assert sorted(calls) == ["https://cdn/rss:friar.mp3", "xyz"]
    yt = rows["yt:xyz"]
    assert yt["has_transcript"] and yt["transcript_source"] == "whisper base.en (3 min, youtube audio)" and "triage" not in manifest(run)
    assert "transcript_source: whisper base.en (3 min, youtube audio)" in (run / yt["file"]).read_text()
    assert rows["rss:friar"]["transcript_source"] == "whisper base.en (3 min)"
    d = status.inspect_run(run)
    STATUS_SHAPE.validate(d)
    assert d["stage"] == "analyse" and d["next"]["type"] == "agent"  # the agent picks the findings; no further command is chosen for it
    failing = custom_run(tmp_path, [pick(episode_id="yt:bad", audio_url=None, youtube_id="bad", title="Unavailable talk")], "failing")

    def blocked(vid, budget):
        raise OSError("blocked")

    monkeypatch.setattr(whisper, "transcribe_youtube", blocked)
    fetch_mod.transcribe_run(targs(failing, top=8, people=None))
    assert manifest(failing)["episodes"][0]["whisper_error"] == "OSError" and (failing / "transcribe.failed.log").exists()


def test_a_youtube_bot_check_waits_then_retries_once_then_gives_up_for_the_run(monkeypatch, tmp_path):
    run = custom_run(tmp_path, [pick(episode_id="yt:xyz", audio_url=None, youtube_id="xyz", title="Altman, staying human"),
                                pick(title="Friar on compute")])
    calls, waits = [], []
    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(fetch_mod.time, "sleep", waits.append)

    def youtube(vid, budget):
        calls.append(vid)
        if calls.count(vid) == 1:
            raise whisper.YouTubeBlocked("bot check")
        return budget.spend(180) or LONG, 180.0

    monkeypatch.setattr(whisper, "transcribe_youtube", youtube)
    monkeypatch.setattr(whisper, "transcribe", lambda url, budget: calls.append(url) or (budget.spend(180) or LONG, 180.0))
    fetch_mod.transcribe_run(targs(run, people=None))
    assert calls.count("xyz") == 2 and calls[-1] == "xyz" and len(waits) == 1
    assert all(e["has_transcript"] for e in manifest(run)["episodes"]) and not (run / "transcribe.failed.log").exists()
    # a second bot check in the same run: YouTube is left alone until the next run
    run = custom_run(tmp_path, [pick(episode_id="yt:a", audio_url=None, youtube_id="a", title="One talk"),
                                pick(episode_id="yt:b", audio_url=None, youtube_id="b", title="Another talk")], "blocked-twice")
    calls.clear()

    def blocked(vid, budget):
        calls.append(vid)
        raise whisper.YouTubeBlocked("bot check")

    monkeypatch.setattr(whisper, "transcribe_youtube", blocked)
    fetch_mod.transcribe_run(targs(run, people=None))
    assert len(calls) == 2  # one before the wait, one after; then YouTube is left alone
    assert not any(e["has_transcript"] or e.get("whisper_error") for e in manifest(run)["episodes"])


def test_transcribe_youtube_names_a_bot_check(monkeypatch):
    import subprocess

    import pytest

    monkeypatch.setattr(whisper, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, "", "ERROR: [youtube] xyz: Sign in to confirm you’re not a bot. Use --cookies"))
    with pytest.raises(whisper.YouTubeBlocked):
        whisper.transcribe_youtube("xyz", whisper.Budget(600))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "ERROR: Video unavailable"))
    with pytest.raises(subprocess.CalledProcessError):
        whisper.transcribe_youtube("xyz", whisper.Budget(600))
