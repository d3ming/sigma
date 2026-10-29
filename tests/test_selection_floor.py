"""The owner's selection floor: at least 3 picks a day, every 6+ picked, the best 5s fill up to 3 (labeled), nothing under 5.
And the transcription side: every episode without a transcript says why, and the default triage cap leaves a day's episodes whole."""
import json

import pytest

from wire import fetch as fetch_mod, report, whisper
from wire import cli
from wire.cli import main
from wire.triage import DEFAULT_TOP
from wire.whisper import Budget

from tests.helpers import LONG, ep, make_run, targs


def pick(eid, name, **kw):
    return {"episode_id": eid, "title": "T", "show": "Show", "url": f"https://show.example/{eid}", "kind": "exec", "why": "new numbers",
            "guests": [{"name": name, "role": "CEO"}], **kw}


def day(tmp_path, scores, **rows):
    """A run folder with a manifest of the scored episodes (rows: per-id manifest overrides) and their scores.json."""
    tmp_path.mkdir(exist_ok=True)
    ids = list(scores)
    (tmp_path / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": i, "title": i, "source": "Show", "has_transcript": True, "fallback_text": False, **rows.get(i, {})} for i in ids]}))
    (tmp_path / "scores.json").write_text(json.dumps({"episodes": [{"episode_id": i, "score": s} for i, s in scores.items()]}))
    return tmp_path


def check(run, picks, left_out=None):
    data = {"date": "2026-10-28", "run_dir": "runs/x", "selected_by": "t", "episodes": picks, **({"left_out": left_out} if left_out else {})}
    report.validate(data, "selected")
    return report.verify("selected", data, run)


def test_every_6_plus_is_picked_and_the_best_5s_fill_up_to_three(tmp_path):
    run = day(tmp_path, {"a": 7, "b": 6, "c": 5, "d": 5, "e": 4})
    ok = [pick("a", "Ann"), pick("b", "Bo"), pick("c", "Cy", lower_confidence=True)]
    assert check(run, ok) == []  # 2 full picks + 1 labeled 5; the second 5 and the 4 are not needed
    assert any("minimum 3" in e and "'c'" in e or "minimum 3" in e for e in check(run, ok[:2]))  # 2 picks while a 5 is available
    assert any("scored 5: set lower_confidence" in e for e in check(run, [pick("a", "Ann"), pick("b", "Bo"), pick("c", "Cy")]))
    assert any("a 6+ is a full pick" in e for e in check(run, [pick("a", "Ann", lower_confidence=True), pick("b", "Bo"), pick("c", "Cy", lower_confidence=True)]))
    assert any("scored 4" in e for e in check(run, [*ok[:2], pick("e", "Ed", lower_confidence=True)]))  # never pad with junk
    assert any("drop it" in e for e in check(run, [*ok, pick("d", "Di", lower_confidence=True)]))  # a 5 only fills up to 3


def test_there_is_no_upper_limit_and_a_6_cannot_be_dropped_for_novelty(tmp_path):
    run = day(tmp_path, {f"s{i}": 6 for i in range(5)})
    picks = [pick(f"s{i}", f"Guest {i}") for i in range(5)]
    assert check(run, picks) == []  # five 6+ picks, no cap
    errs = check(run, picks[:4])
    assert len(errs) == 1 and "s4 scored 6 but is neither picked nor in left_out" in errs[0]
    assert check(run, picks[:4], [{"episode_id": "s4", "reason": "repeat_appearance"}]) == []
    with pytest.raises(Exception):  # "not new enough" is not an allowed reason for leaving a 6+ out
        check(run, picks[:4], [{"episode_id": "s4", "reason": "not_novel"}])
    assert any("also picked" in e for e in check(run, picks, [{"episode_id": "s4", "reason": "recap"}]))


def test_a_quiet_day_and_hard_rules_may_leave_it_under_three(tmp_path):
    quiet = day(tmp_path / "q", {"a": 6, "b": 3})
    assert check(quiet, [pick("a", "Ann")]) == []  # nothing else scores 5+: pick what there is, never pad
    run = day(tmp_path / "h", {"a": 6, "b": 5, "c": 5})
    errs = check(run, [pick("a", "Ann")])
    assert len(errs) == 1 and "minimum 3" in errs[0]
    hard = [{"episode_id": "b", "reason": "hosts_only"}, {"episode_id": "c", "reason": "speaker_other"}]
    assert check(run, [pick("a", "Ann")], hard) == []  # a rule rejects both: nothing left to fill with
    soft = [{"episode_id": "b", "reason": "not_decision_relevant"}, {"episode_id": "c", "reason": "hosts_only"}]
    assert check(run, [pick("a", "Ann")], soft) != []  # a judgment call does not excuse the floor
    # news shows and reruns are not candidates: they need no pick and no entry
    run = day(tmp_path / "n", {"a": 6, "b": 7, "c": 6}, b={"news": True}, c={"rerun": True})
    assert check(run, [pick("a", "Ann")]) == []


def test_the_floor_counts_podcast_interviews_only_never_social_or_influencer_videos(tmp_path):
    run = day(tmp_path, {"a": 7, "b": 6, "c": 5})
    m = json.loads((run / "manifest.json").read_text())
    for i in ("v1", "v2"):
        m["episodes"].append({"episode_id": i, "title": i, "source": "Creator", "style": "influencer", "has_transcript": True, "fallback_text": True})
    (run / "manifest.json").write_text(json.dumps(m))
    two_plus_videos = [pick("a", "Ann"), pick("b", "Bo"), pick("v1", "Vi", fallback_text=True, why="fallback: description only"),
                       pick("v2", "Vu", fallback_text=True, why="fallback: description only")]
    errs = check(run, two_plus_videos)
    assert sum("influencer (Social) episode is not a podcast pick" in e for e in errs) == 2
    assert any("minimum 3" in e for e in check(run, two_plus_videos[:2]))  # 2 podcast picks + available 5: still short
    assert check(run, [pick("a", "Ann"), pick("b", "Bo"), pick("c", "Cy", lower_confidence=True)]) == []


def test_without_scores_the_floor_is_not_checked_and_a_description_only_pick_needs_no_score(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "manifest.json").write_text(json.dumps({"episodes": [{"episode_id": "a", "has_transcript": True, "fallback_text": False}]}))
    assert check(bare, [pick("a", "Ann")]) == []
    run = day(tmp_path / "s", {"a": 7})
    m = json.loads((run / "manifest.json").read_text())
    m["episodes"].append({"episode_id": "f", "has_transcript": False, "fallback_text": True})
    (run / "manifest.json").write_text(json.dumps(m))
    assert check(run, [pick("a", "Ann"), pick("f", "Fay", fallback_text=True, why="fallback text only")]) == []


def test_the_report_carries_the_lower_confidence_label(tmp_path):
    from tests.test_daily import report_json
    d = report_json()
    d["essential"][0]["lower_confidence"] = True
    assert report.render(d).count("(lower confidence)") == 1
    sel = {"date": "x", "run_dir": "r", "selected_by": "t", "episodes": [pick(e["episode_id"], "G") for e in d["essential"]]}
    (tmp_path / "selected.json").write_text(json.dumps(sel))
    assert any("lower_confidence differs" in e for e in report._verify_report(d, {}, tmp_path))


# ---- transcription: no silent skips

def test_the_default_triage_cap_is_wide_and_every_gap_has_a_reason(monkeypatch, tmp_path):
    assert DEFAULT_TOP == 30
    got, real = {}, cli.transcribe_run
    monkeypatch.setattr(cli, "daily", lambda a: got.update(daily=a))
    monkeypatch.setattr(cli, "transcribe_run", lambda a: got.update(transcribe=a))
    main(["daily"])
    main(["transcribe", "x"])
    assert (got["daily"].top, got["daily"].minutes, got["daily"].hours) == (DEFAULT_TOP, 900, 72)
    assert (got["transcribe"].top, got["transcribe"].minutes) == (DEFAULT_TOP, 900)
    monkeypatch.setattr(cli, "transcribe_run", real)
    eps = [ep(f"rss:e{i}", f"Founder {i} on chips", f"show{i}") for i in range(4)]
    run = make_run(tmp_path / "r", [*eps, ep("rss:n", "Halftime", "cnbc-halftime"), ep("rss:rr", "Replay of old", "show9")],
                   **{"rss:n": {"news": True}, "rss:rr": {"rerun": True}})
    monkeypatch.setattr(whisper, "available", lambda: True)
    calls = []
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: calls.append(url) or (LONG, 60.0))
    main(["transcribe", str(run), "--people", ""])  # the default top
    rows = {e["episode_id"]: e for e in json.loads((run / "manifest.json").read_text())["episodes"]}
    assert len(calls) == 4 and all(rows[f"rss:e{i}"]["has_transcript"] and "transcribe_skip" not in rows[f"rss:e{i}"] for i in range(4))
    assert "news or market-recap" in rows["rss:n"]["transcribe_skip"] and "rerun" in rows["rss:rr"]["transcribe_skip"]
    run2 = make_run(tmp_path / "r2", [ep(f"rss:f{i}", f"Operator {i} on grid power", f"other{i}") for i in range(4)])
    main(["transcribe", str(run2), "--people", "", "--top", "2", "--no-tier1-floor"])
    rows = list(json.loads((run2 / "manifest.json").read_text())["episodes"])
    why = [e["transcribe_skip"] for e in rows if not e["has_transcript"]]
    assert len(why) == 2 and all(w.startswith("triage cap: rank") and "below the top 2" in w for w in why)
    main(["transcribe", str(run2), "--people", "", "--top", "0", "--no-tier1-floor"])  # a wider rerun transcribes them and clears the reason
    assert all(e["has_transcript"] and "transcribe_skip" not in e for e in json.loads((run2 / "manifest.json").read_text())["episodes"])


def test_skip_reasons_cover_budget_failure_youtube_and_clips():
    b = Budget(10)
    base = {"episode_id": "x", "has_transcript": False, "audio_url": "https://cdn.example/x.mp3"}
    kw = dict(top=30, skip_news=True, reruns=False, retry=False, tried=set(), yt_left=set(), budget=b)
    assert fetch_mod.skip_reason({**base, "has_transcript": True}, **kw) is None
    assert "audio budget used up (0 of 10 min)" in fetch_mod.skip_reason(base, **kw)
    assert fetch_mod.skip_reason({**base, "whisper_error": "empty"}, **{**kw, "tried": {"x"}}) == "whisper failed: empty"
    assert "--retry-errors" in fetch_mod.skip_reason({**base, "whisper_error": "empty"}, **kw)
    assert "YouTube bot check" in fetch_mod.skip_reason(base, **{**kw, "yt_left": {"x"}})
    assert "clip of full" in fetch_mod.skip_reason({**base, "triage": {"reasons": ["clip of full"], "whisper": False}}, **kw)
    assert fetch_mod.skip_reason({"episode_id": "x", "has_transcript": False}, **kw) == "no audio or YouTube source to transcribe"
