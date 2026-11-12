"""theta#93: a budget-cut transcript is never complete or reused, the fullest copy of the same media wins, and a stored
score is checked against the transcript it was made on."""
import json
from datetime import datetime, timezone

from sigma import fetch as fetch_mod, library, rank, ranked, scoreaudit, status, transcripts, whisper
from sigma.ingest import Episode
from tests.helpers import targs

AUDIO = "https://traffic.megaphone.fm/CLS5603610979.mp3"


def episode(eid="rss:sosin", duration=3649):
    return Episode(id=eid, source_id="iltb", source_name="Invest Like the Best", tier=1, title=f"Episode {eid}", url="https://show/e",
                   published_at=datetime(2026, 10, 27, tzinfo=timezone.utc), audio_url=AUDIO if eid == "rss:sosin" else None if eid.startswith("x:") else f"https://cdn/{eid}.mp3",
                   duration=duration)


def segs(end, word="word"):
    return [{"start": float(t), "speaker": None, "text": f"{word} {t} " * 20} for t in [*range(0, end, 60), end]]


def run(runs, name, *items):
    d = runs / name
    d.mkdir(parents=True)
    rows = [fetch_mod.write_episode(d, e, s, label) for e, s, label in items]
    (d / "manifest.json").write_text(json.dumps({"episodes": rows}))
    return d


def rows(d):
    return {e["episode_id"]: e for e in json.loads((d / "manifest.json").read_text())["episodes"]}


def test_a_budget_cut_transcript_is_never_complete_or_reused_and_the_fullest_same_media_copy_wins(monkeypatch, tmp_path):
    """Failure seen: whisper stopped at 49 of the 61 minutes of an episode; the 80% transcript was scored and reused while
    a 62.5-minute copy of the same audio sat in a later run."""
    runs = tmp_path / "runs"
    run(runs, "2026-10-27", (episode(), segs(2928), "whisper large-v3-turbo (49 min)"))
    run(runs, "2026-10-31-bucco", (episode(), segs(3750), "whisper large-v3-turbo (63 min)"))
    run(runs, "2026-11-01-adshift", (episode(duration=3900), segs(3900), "whisper large-v3-turbo (65 min)"))
    run(runs, "2026-11-02-weekly", (episode("x:nomedia"), segs(4200, "talk"), "whisper large-v3-turbo (70 min)"))
    run(tmp_path / "archive", "2026-10-27", (episode(), segs(2928), "whisper large-v3-turbo (49 min)"))
    (tmp_path / "operator.json").write_text(json.dumps({"legacy_transcripts": ["archive"]}))
    (runs / "2026-10-27" / "scores.json").write_text(json.dumps({"episodes": [{"episode_id": "rss:sosin", "score": 5}]}))
    new = run(runs, "2026-11-04", (episode(), None, None), (episode("rss:other"), None, None))
    monkeypatch.setattr(whisper, "available", lambda: True)
    calls = []
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: calls.append(url) or (b.spend(2940) or segs(2928), 2940.0, 3649.0))
    fetch_mod.transcribe_run(targs(new, top=0, people=None))
    got = rows(new)
    assert calls == ["https://cdn/rss:other.mp3"]
    assert got["rss:sosin"]["has_transcript"] and got["rss:sosin"]["transcript_source"] == "whisper large-v3-turbo (63 min)"
    assert "[1:02:30]" in (new / got["rss:sosin"]["file"]).read_text()
    cut = got["rss:other"]
    assert not cut["has_transcript"] and cut["transcript_complete"] is False and cut["media_seconds"] == 3649
    assert cut["transcribe_skip"].startswith("partial transcript (49 of 61 min)")
    assert "transcript_complete: false" in (new / cut["file"]).read_text()
    assert status.inspect_run(new)["transcribe"]["whisper_pending"] == 1
    assert fetch_mod.ReuseIndex(runs).find(cut) is None
    index = fetch_mod.ReuseIndex(runs, exclude=new)
    for eid in ("x:nomedia",):  # failure seen in review: an episode with no media keys
        assert index.find(rows(runs / "2026-11-02-weekly")[eid])[2].startswith("2026-11-02-weekly/")

    found = transcripts.locate(tmp_path, "rss:sosin")
    assert found["chosen"]["run"] == "2026-10-31-bucco" and (found["chosen"]["minutes"], found["chosen"]["media_minutes"]) == (62.5, 60.8)
    assert {(s["path"].split("/")[-3], s["run"], s["reason"]) for s in found["skipped"]} == {
        ("runs", "2026-10-27", "whisper stopped at 49 of 61 min"), ("runs", "2026-11-01-adshift", "different media"),
        ("runs", "2026-11-04", "same length"), ("archive", "2026-10-27", transcripts.LEGACY)}

    report = scoreaudit.audit(tmp_path)
    assert report["flagged"] == [{"run": "2026-10-27", "episode_id": "rss:sosin", "score": 5, "published": False, "file": "scores.json",
                                  "reasons": ["whisper stopped at 49 of 61 min", "coverage 80%",
                                              "fuller copy of the same media in 2026-10-31-bucco (62.5 vs 48.8 min)"]}]
    assert report["unverifiable_legacy"] == 1


def score_out(d, score):
    r = next(iter(rows(d).values()))
    (d / "rank" / "batch-1-out.json").write_text(json.dumps([{**{k: r[k] for k in ("episode_id", "title", "url", "source", "tier", "published")},
                                                             "score": score, "reason": "r", "claims": []}]))


def test_a_reused_score_is_checked_against_the_transcript_it_was_made_on_and_never_dropped(tmp_path):
    """Stated rule (theta#93): reuse is verified only on a matching transcript record; a mismatch or a legacy score with no
    record keeps its score, stays ranked and is listed for review; the library keeps the record of the scoring run."""
    runs, db = tmp_path / "runs", tmp_path / "library.sqlite"
    old = run(runs, "2026-10-20", (episode("rss:legacy"), segs(3600, "other"), "podcast:transcript"))
    (old / "scores.json").write_text(json.dumps({"rubric": rank.rubric_version(), "episodes": [
        {**{k: rows(old)["rss:legacy"][k] for k in ("episode_id", "title", "url", "source", "tier", "published")},
         "score": 6, "reason": "r", "claims": []}]}))
    library.ingest_run(old, db=db)
    (old / rows(old)["rss:legacy"]["file"]).unlink()

    first = run(runs, "2026-10-27", (episode(), segs(2928), "podcast:transcript"))
    rank.prep(first, db=db)
    score_out(first, 5)
    data = rank.merge(first, "test", ranking=False)
    assert {k: data["episodes"][0]["transcript"][k] for k in ("end_seconds", "media_seconds")} == {"end_seconds": 2928, "media_seconds": 3649}
    (first / "scores.json").write_text(json.dumps(data))
    library.ingest_run(first, db=db)

    same = run(runs, "2026-10-28", (episode(), segs(2928), "podcast:transcript"))
    assert rank.prep(same, db=db)["stored"] == 1
    stored = json.loads((same / "rank" / "stored.json").read_text())[0]
    assert "score_check" not in stored and stored["transcript"] == data["episodes"][0]["transcript"]

    week = run(runs, "2026-11-02-weekly", (episode(), segs(3750), "podcast:transcript"), (episode("rss:legacy"), segs(3600, "other"), "podcast:transcript"))
    stats = rank.prep(week, db=db)
    assert (stats["stored"], stats["to_score"], stats["mismatch"], stats["unverifiable"]) == (2, 0, 1, 1)
    merged = rank.merge(week, "test")
    ranked.validate(merged)
    assert {(e["episode_id"], e["score"], e["scored_in"], e.get("score_check")) for e in merged["episodes"]} == {
        ("rss:sosin", 5, "2026-10-27", "mismatch"), ("rss:legacy", 6, "2026-10-20", "unverifiable")}
    (week / "ranked.json").write_text(json.dumps(merged))
    library.ingest_run(week, db=db)
    kept = library.stored_scores(["rss:sosin"], db, rubric=rank.rubric_version())["rss:sosin"]
    assert (kept["score"], kept["scored_run"], kept["transcript"]["end_seconds"]) == (5, "2026-10-27", 2928)

    report = scoreaudit.audit(tmp_path)
    assert [(f["run"], f["episode_id"], f["reasons"]) for f in report["flagged"]] == [
        ("2026-10-20", "rss:legacy", ["no transcript on disk for the scoring run"]),
        ("2026-10-27", "rss:sosin", ["coverage 80%", "fuller copy of the same media in 2026-11-02-weekly (62.5 vs 48.8 min)"]),
        ("2026-11-02-weekly", "rss:sosin", ["record mismatch (scored on 48.8 min, now 62.5 min)"])]
    assert (report["scores"], report["unverifiable_legacy"]) == (4, 2)
