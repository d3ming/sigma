"""The weekly run as an agent runs it (prompts/weekly.md): rank-prep -> readers -> rank-merge -> themes-check -> publish.

Every step goes through sigma.cli.main. The readers (agents) are played by the test, which writes rank/batch-N-out.json
from each batch-N-in.json the way prompts/rank.md says."""
import io
import json
import os
import shutil
from contextlib import redirect_stdout
from datetime import datetime, timezone

import pytest

from sigma import library, published, ranked as ranked_mod, report
from sigma.cli import after_stage, main
from sigma.fetch import write_episode
from sigma.ingest import Episode
from sigma.transcribe import MIN_TRANSCRIPT_CHARS

from tests.helpers import STATUS_SHAPE, sandbox, spoken

RUN = "2026-10-19-weekly"
AD = "this episode is brought to you by acme corp " * 8


def test_claim_grounding_fails_closed_without_a_manifest_or_transcript(tmp_path):
    data = {"episodes": [{"episode_id": "ep1", "claims": [{"claim": "Demand is growing.", "timestamp": 10}]}]}
    errors, warnings = report.ranked_check(data, tmp_path)
    assert errors and "manifest.json is missing or unreadable" in errors[0][2] and not warnings
    (tmp_path / "manifest.json").write_text("{")
    errors, warnings = report.ranked_check(data, tmp_path)
    assert errors and "manifest.json is missing or unreadable" in errors[0][2] and not warnings
    (tmp_path / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": "ep1", "has_transcript": True, "file": "missing.md"}]}))
    errors, warnings = report.ranked_check(data, tmp_path)
    assert errors and "claims cannot be grounded" in errors[0][2] and not warnings


def test_claim_speaker_must_match_an_explicit_label_at_the_cited_segment(tmp_path):
    assert report._explicit_speaker("The point is: demand will rise through next year.") is None
    assert report._explicit_speaker("Host: Demand will rise through next year.") == "Host"
    assert report._explicit_speaker("Actual speaker (CEO): Demand will rise through next year.") == "Actual speaker (CEO)"
    (tmp_path / "e1.md").write_text("## Transcript\n\n[0:00:10] Actual speaker: Demand will rise through next year.\n"
                                      "[0:00:12] A separate comment follows without a speaker label.\n")
    (tmp_path / "e2.md").write_text("## Transcript\n\n[0:00:30] Demand will rise through next year.\n")
    (tmp_path / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": "ep1", "has_transcript": True, "file": "e1.md"},
        {"episode_id": "ep2", "has_transcript": True, "file": "e2.md"}]}))
    ranked = {"episodes": [
        {"episode_id": "ep1", "claims": [{"claim": "Demand will rise through next year.", "speaker": "Wrong speaker", "timestamp": 10},
                                             {"claim": "A separate comment follows.", "speaker": "Wrong speaker", "timestamp": 13}]},
        {"episode_id": "ep2", "claims": [{"claim": "Demand will rise through next year.", "speaker": "Unlabeled speaker", "timestamp": 30}]}]}
    errors, warnings = report.ranked_check(ranked, tmp_path)
    assert len(errors) == 1 and "speaker 'Wrong speaker' does not match transcript label 'Actual speaker'" in errors[0][2]
    assert not warnings
    daily = {"essential": [], "episodes": [
        {"episode_id": "ep1", "signal": [{"text": "Demand will rise through next year.", "speaker": "Wrong speaker", "timestamp": 10},
                                             {"text": "A separate comment follows.", "speaker": "Wrong speaker", "timestamp": 13}], "sections": []},
        {"episode_id": "ep2", "signal": [{"text": "Demand will rise through next year.", "speaker": "Unlabeled speaker", "timestamp": 30}], "sections": []}]}
    errors = report.verify("report", daily, tmp_path)
    assert len(errors) == 1 and "speaker 'Wrong speaker' does not match transcript label 'Actual speaker'" in errors[0]
    ranked["episodes"][0]["claims"][0]["timestamp"] = 11
    daily["episodes"][0]["signal"][0]["timestamp"] = 11
    errors, warnings = report.ranked_check(ranked, tmp_path)
    assert len(errors) == 1 and "speaker 'Wrong speaker' does not match transcript label 'Actual speaker'" in errors[0][2]
    assert not warnings
    errors = report.verify("report", daily, tmp_path)
    assert len(errors) == 1 and "speaker 'Wrong speaker' does not match transcript label 'Actual speaker'" in errors[0]
    ranked["episodes"][0]["claims"][0]["speaker"] = "Actual speaker"
    daily["episodes"][0]["signal"][0]["speaker"] = "Actual speaker"
    assert report.ranked_check(ranked, tmp_path) == ([], [])
    assert report.verify("report", daily, tmp_path) == []

# id: (show, tier, reader score, published, filler word, what is said at 5:00, claims as (ticker, claim, speaker))
SAID = {
    "a": "we think demand for accelerators will outrun supply well into next year and beyond for sure",
    "b": "our foundry partner has no spare advanced packaging room until the second half of the year",
    "c": "hyperscalers keep raising spending plans every single quarter and nobody there is blinking at all",
    "d": "the smaller challenger is winning design slots because buyers want a second source of supply",
    "e": "power and cooling are now the real bottleneck for new capacity in every region we looked at",
}
EPISODES = {
    "a": ("Show A", 1, 9, "2026-10-18", "signals", [("NVDA", "Accelerator demand stays ahead of supply into next year", "Ann Lee"),
                                                  ("AMD", "Buyers are qualifying a second chip supplier", "Ann Lee"),
                                                  ("", "The panel liked the venue", "Pat Moss (host)")]),
    "a2": ("Show A on a second feed", 1, 4, "2026-10-17", "signals", []),  # the same transcript as a
    "b": ("Show B", 1, 8, "2026-10-18", "bravo", [("nvda", "Packaging capacity at the foundry is fully booked", "Bo Chen"),
                                                  ("TSM", "Foundry expansion lands late in the year", "Bo Chen")]),
    "c": ("Show A", 1, 7, "2026-10-18", "charlie", [("TSM", "Cloud spending plans rise again", "Ann Lee (founder)"),
                                                    ("", "The panel liked the venue", "Pat Moss")]),  # the host, named without a role
    "d": ("Show C", 1, 6, "2026-10-17", "delta", [("AMD", "Design wins are shifting toward the challenger", "Di Fox"),
                                                  ("", "The room was full", "Pat Moss")]),
    "e": ("Show D", 2, 5, "2026-10-16", "echo", [("private:Acme", "Power is the limit on new data centers", "Ed Gray")]),
    "g": ("Show G", 3, 10, "2026-10-18", "golf", []),
    "h": ("Show H", 1, 3, "2026-10-15", "hotel", []),
    "i": ("Show I", 3, 2, "2026-10-15", "india", []),
    "j": ("Show J", 3, 1, "2026-10-15", "juliet", []),
}
INTRO = {"d": {s: AD for s in range(0, 300, 60)}, "h": {s: AD for s in range(0, 300, 60)}}  # an ad read both begin with


def url(i):
    return "https://www.youtube.com/watch?v=aaaaaaaaaaa" if i == "a" else f"https://example.com/{i}"


@pytest.fixture
def week(tmp_path, monkeypatch):
    """runs/<week> as `fetch` and `transcribe` leave it: 10 transcribed episodes (two feeds carry the same one) and 1 without text."""
    root = sandbox(tmp_path, monkeypatch)
    run = root / "runs" / RUN
    run.mkdir(parents=True)
    rows = []
    for i, (show, tier, _, day, word, claims) in EPISODES.items():
        lines = {**INTRO.get(i, {}), **({300: SAID[i]} if i in SAID else {}), **({300: SAID["a"]} if i == "a2" else {})}
        times = sorted({0, 60, 120, 180, 240, 300, 310, 320, 1740})
        segs = [{"start": t, "speaker": None, "text": lines.get(t, f"{word} " * 10).strip()} for t in times if t < 1740]
        filler_chars = MIN_TRANSCRIPT_CHARS + 1 - sum(len(s["text"]) + 1 for s in segs)
        filler_words = max(1, (filler_chars + len(word)) // (len(word) + 1))
        segs.append({"start": 1740, "speaker": None, "text": f"{word} " * filler_words})
        ep = Episode(id=f"rss:{i}", source_id=show.lower().replace(" ", "-"), source_name=show, tier=tier, title=f"Episode {i}", url=url(i),
                     published_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc))
        rows.append(write_episode(run, ep, segs, "podcast:transcript"))
    ep = Episode(id="rss:x", source_id="show-x", source_name="Show X", tier=1, title="Episode x", url=url("x"),
                 published_at=datetime(2026, 10, 18, tzinfo=timezone.utc))
    rows.append(write_episode(run, ep, None, None))
    rows[1]["title"] = "Episode a (second feed)"
    (run / "manifest.json").write_text(json.dumps({"days": 7, "episodes": rows}))
    return root


def status(run):
    out = io.StringIO()
    with redirect_stdout(out):
        main(["status", str(run), "--json", "--weekly"])
    STATUS_SHAPE.validate(d := json.loads(out.getvalue()))
    return d


def read_batches(run):
    """What the readers do: score every episode in each batch-N-in.json and save batch-N-out.json."""
    for f in sorted((run / "rank").glob("batch-*-in.json")):
        out = []
        for item in json.loads(f.read_text()):
            i = item["episode_id"].split(":")[1]
            _, _, score, _, _, claims = EPISODES[i]
            out.append({**{k: item[k] for k in ("episode_id", "title", "url", "source", "tier", "published")}, "score": score, "reason": "why",
                        "claims": [{"ticker": [t] if t else [], "claim": c, "speaker": sp, "timestamp": 300 + 10 * n, "novelty": 1, "verifiable": 1}
                                   for n, (t, c, sp) in enumerate(claims)]})
        f.with_name(f.name.replace("-in", "-out")).write_text(json.dumps(out))


@pytest.fixture
def ranked_week(week):
    run = week / "runs" / RUN
    main(["rank-prep", str(run)])
    read_batches(run)
    main(["rank-merge", str(run)])
    return run


def themes_json():
    return {"week_of": "2026-10-15", "run": RUN, "headline": "Chip supply is the constraint and buyers are looking for a second source.",
            "themes": [
                {"title": "Accelerator supply stays short", "stance": "consensus", "tickers": ["nvda"],
                 "summary": "Two shows said demand outruns supply through next year. Neither saw relief before the foundry adds packaging room.",
                 "episode_ids": ["rss:a", "rss:b", "rss:c"], "evidence": [{"episode_id": "rss:a", "claim_index": 0}, {"episode_id": "rss:b", "claim_index": 0}]},
                {"title": "Foundry timing", "stance": "emerging", "tickers": ["TSM"],
                 "summary": "One guest expects expansion late in the year while a cloud operator keeps raising plans, so the gap may persist.",
                 "episode_ids": ["rss:b", "rss:c"], "evidence": [{"episode_id": "rss:b", "claim_index": 1}, {"episode_id": "rss:c", "claim_index": 0}]},
                {"title": "A second chip source", "stance": "split", "tickers": ["AMD"],
                 "summary": "Buyers want a second supplier, but one side says design wins are real and the other says volume is small.",
                 "episode_ids": ["rss:a", "rss:d", "rss:e"], "evidence": [{"episode_id": "rss:a", "claim_index": 1}, {"episode_id": "rss:d", "claim_index": 0}]}]}


def edit(path, fn):
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def ep_row(data, i):
    return next(e for e in data["episodes"] if e["episode_id"] == f"rss:{i}")


def test_an_episode_is_scored_once_and_a_blind_re_score_never_replaces_it(week, capsys, monkeypatch):
    """prompts/rank.md: the first run to transcribe an episode scores it and the library keeps that score; a later run reads
    only the unscored ones, and re-scoring stored episodes blind is an eval that measures drift. An episode from a
    `style: influencer` source (stated rule) is read under prompts/rank-influencer.md and lands in
    scores-influencer.json, never in the ranking, even with a 10 that would put it first."""
    root, first = week, week / "runs" / RUN
    monkeypatch.delenv("SIGMA_NO_LIBRARY")
    monkeypatch.setattr(library, "DEFAULT_DB", root / "lib.sqlite")
    k = Episode(id="rss:k", source_id="show-k", source_name="Show K", tier=2, style="influencer", title="Episode k", url=url("k"),
                published_at=datetime(2026, 10, 18, tzinfo=timezone.utc))
    row = write_episode(first, k, spoken({300: "we like the chip maker here and would trim under the fifty day line"}, filler="kilo", every=10),
                        "podcast:transcript")
    edit(first / "manifest.json", lambda m: m["episodes"].append(row))
    main(["rank-prep", str(first)])
    read_batches(first)
    for f in first.glob("rank/batch-*-out.json"):  # the first run's readers scored only b (8) and d (6)
        edit(f, lambda rows: rows.__setitem__(slice(None), [r for r in rows if r["episode_id"] in ("rss:b", "rss:d")]))
    assert not any("rss:k" in f.read_text() for f in first.glob("rank/batch-*-in.json"))
    influencer_in = first / "rank" / "influencer-1-in.json"
    assert [e["episode_id"] for e in json.loads(influencer_in.read_text())] == ["rss:k"]
    assert (d := status(first))["stage"] == "readers" and "rank-influencer.md" in d["next"]["summary"]
    kay = {"ticker": ["NVDA"], "claim": "Would trim the chip maker on a close under the fifty day line", "speaker": "Kay Host",
           "timestamp": 300, "novelty": 1, "verifiable": 3}
    influencer_row = {"episode_id": "rss:k", "title": "Episode k", "url": url("k"), "source": "Show K", "tier": 2, "published": "2026-10-18",
                      "score": 10, "reason": "why", "claims": [kay]}
    (first / "rank" / "influencer-1-out.json").write_text(json.dumps([influencer_row]))
    batch_out = first / "rank" / "batch-1-out.json"
    leaked = batch_out.read_text()  # a reader who scores the influencer episode under rank.md instead: refused, nothing written
    edit(batch_out, lambda rows: rows.append(influencer_row))
    with pytest.raises(SystemExit):
        main(["rank-merge", str(first)])
    assert not (first / "ranked.json").exists()
    batch_out.write_text(leaked)
    main(["rank-merge", str(first)])
    assert "rss:k" not in {e["episode_id"] for e in json.loads((first / "ranked.json").read_text())["episodes"]}
    apart = json.loads((first / "scores-influencer.json").read_text())
    assert [(e["episode_id"], e["score"]) for e in apart["episodes"]] == [("rss:k", 10)] and apart["rubric"] == 1
    assert library.stored_scores(["rss:k"]) == {}  # the interview lookup never sees it
    assert library.stored_scores(["rss:k"], rubric=1, style="influencer")["rss:k"]["score"] == 10

    later = root / "runs" / "2026-10-26-weekly"
    shutil.copytree(first, later, ignore=shutil.ignore_patterns("rank", "ranked.json", "digest*"))
    capsys.readouterr()
    main(["rank-prep", str(later), "--eval", "2"])
    assert "8 of 10 transcribed episodes to score" in capsys.readouterr().out
    read_ids = {e["episode_id"] for f in later.glob("rank/batch-*-in.json") for e in json.loads(f.read_text())}
    assert read_ids == {f"rss:{i}" for i in ("a", "a2", "c", "e", "g", "h", "i", "j")}  # b and d are not read again
    assert not list(later.glob("rank/influencer-*-in.json"))  # k keeps its stored influencer score
    assert [(e["episode_id"], e["scored_in"]) for e in json.loads((later / "rank" / "influencer-stored.json").read_text())] == [("rss:k", RUN)]
    assert {e["episode_id"] for e in json.loads((later / "rank" / "eval-in.json").read_text())} == {"rss:b", "rss:d"}
    read_batches(later)
    # blind re-scores: d 6 -> 5 and b 8 -> 6. By hand: mean (-1 - 2) / 2 = -1.5, mean absolute (1 + 2) / 2 = 1.5, one within
    # 1 point, and only d crosses the curated-selection cutoff of 6 (select.md: candidates score 6 or more)
    (later / "rank" / "eval-out.json").write_text(json.dumps([{"episode_id": "rss:d", "score": 5, "reason": "again"},
                                                              {"episode_id": "rss:b", "score": 6, "reason": "again"}]))
    capsys.readouterr()
    main(["rank-merge", str(later)])
    assert "2 stored episodes re-scored blind: mean change -1.5, mean absolute 1.5, 1 within 1 point, 1 crossed the 6 bar" in capsys.readouterr().out
    rows = {e["episode_id"]: e for e in json.loads((later / "ranked.json").read_text())["episodes"]}
    assert (rows["rss:b"]["score"], rows["rss:b"]["scored_in"]) == (8, RUN) and (rows["rss:d"]["score"], rows["rss:d"]["scored_in"]) == (6, RUN)
    assert "scored_in" not in rows["rss:a"]
    kept = library.stored_scores(["rss:b", "rss:d"])  # the library still holds the first run's scores, not the eval's
    assert (kept["rss:b"]["score"], kept["rss:d"]["score"]) == (8, 6)


def test_publish_refuses_ungrounded_rankings(ranked_week, tmp_path, monkeypatch):
    """prompts/rank.md and AGENTS.md: a ranking that breaks a rule, or a claim the transcript does not support, publishes nothing."""
    run, root = ranked_week, ranked_week.parent.parent
    monkeypatch.setattr(published, "ROOT", root / "data" / "published")
    monkeypatch.delenv("SIGMA_NO_PUBLISHED")
    ranked = (run / "ranked.json").read_text()
    manifest = (run / "manifest.json").read_text()
    said = SAID["a"]

    ranking_cases = {
        "a score of 11": lambda d: ep_row(d, "a").update(score=11),
        "a field outside the schema": lambda d: ep_row(d, "a").update(weight=0.1),
        "ranks that skip": lambda d: ep_row(d, "b").update(rank=5),
        "tier 3 in the top 3": lambda d: ep_row(d, "b").update(tier=3),
        "three tier-3 episodes": lambda d: [ep_row(d, i).update(tier=3) for i in "dh"] and ep_row(d, "e").update(tier=3),
    }
    for why, mutate in ranking_cases.items():
        data = json.loads(ranked)
        mutate(data)
        with pytest.raises(ranked_mod.RankedError):
            ranked_mod.validate(data)
    private = json.loads(ranked)
    ep_row(private, "a").update(reason="holding 5% of NVDA")
    (run / "ranked.json").write_text(json.dumps(private))
    with pytest.raises(SystemExit, match="holdings data"):
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert not list(run.glob("digest-*.md")) and not (root / "data" / "published").exists()
    bad_claims = json.loads(ranked)
    ep_row(bad_claims, "a")["claims"][0].update(timestamp=4000, claim=said)
    ep_row(bad_claims, "b")["episode_id"] = "rss:nope"
    (run / "ranked.json").write_text(json.dumps(bad_claims))
    with pytest.raises(SystemExit) as refusal:
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert all(msg in str(refusal.value) for msg in ("not in manifest.json", "past the end of the transcript", "copied verbatim"))
    assert not list(run.glob("digest-*.md")) and not (root / "data" / "published").exists()
    (run / "ranked.json").write_text(ranked)
    edit(run / "manifest.json", lambda m: next(e for e in m["episodes"] if e["episode_id"] == "rss:b").update(has_transcript=False))
    with pytest.raises(SystemExit):
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert not list(run.glob("digest-*.md"))
    # eleven copied words are a paraphrase
    (run / "manifest.json").write_text(manifest)
    edit(run / "ranked.json", lambda d: ep_row(d, "a")["claims"][0].update(claim=" ".join(said.split()[:11])))
    main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert list(run.glob("digest-*.md")) and (root / "data" / "published" / RUN / "ranked.json").exists()


def test_ranking_with_claims_without_a_manifest_is_refused(ranked_week, capsys):
    """Claim-bearing rankings cannot be published when their manifest is unavailable."""
    run = ranked_week
    (run / "manifest.json").unlink()
    edit(run / "ranked.json", lambda d: ep_row(d, "a").update(url=""))
    capsys.readouterr()
    with pytest.raises(SystemExit, match="cannot ground claims"):
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert not list(run.glob("digest-*.md"))


def test_number_grounding_warnings_block_digest_publication(ranked_week):
    run = ranked_week
    edit(run / "ranked.json", lambda d: ep_row(d, "a")["claims"][0].update(claim="Revenue grew 93%."))
    with pytest.raises(SystemExit, match="number 93 not spoken"):
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert not list(run.glob("digest-*.md"))


def test_failed_public_export_stops_before_persistent_library_ingest(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("grounding failed")

    monkeypatch.delenv("SIGMA_NO_PUBLISHED", raising=False)
    monkeypatch.delenv("SIGMA_NO_LIBRARY", raising=False)
    monkeypatch.setattr(published, "export", refuse)
    ingested = []
    monkeypatch.setattr(library, "ingest_run", lambda *args, **kwargs: ingested.append(args))
    with pytest.raises(SystemExit, match="not exported.*grounding failed"):
        after_stage(tmp_path, ingest=True)
    assert ingested == []


def test_publish_refuses_invalid_themes_and_writes_nothing(ranked_week, monkeypatch):
    run, root = ranked_week, ranked_week.parent.parent
    monkeypatch.setattr(published, "ROOT", root / "data" / "published")
    monkeypatch.delenv("SIGMA_NO_PUBLISHED")
    data = themes_json()
    data["themes"][1]["evidence"][1] = {"episode_id": "rss:c", "claim_index": 4}
    (run / "themes.json").write_text(json.dumps(data))
    with pytest.raises(SystemExit) as e:
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert "[publish] invalid: themes: themes[1] 'Foundry timing': evidence[1] (rss:c claims[4])" in str(e.value)
    assert not list(run.glob("digest-*.md")) and not (root / "data" / "published").exists()
    # export-published: a good file exports; a later refusal leaves the earlier export alone
    (run / "themes.json").write_text(json.dumps(themes_json()))
    main(["export-published", str(run), "--top", "5"])
    assert (root / "data" / "published" / RUN / "themes.json").exists()
    with pytest.raises(SystemExit, match=r"\[published\] invalid: themes: themes\[2\]"):
        main(["export-published", str(run), "--top", "4"])
    assert (root / "data" / "published" / RUN / "themes.json").exists()
    # a re-export replaces the folder, so a file dropped from the run does not linger; a run with nothing to publish is refused
    (root / "data" / "published" / RUN / "stale.txt").write_text("old")
    main(["export-published", str(run), "--top", "5"])
    assert not (root / "data" / "published" / RUN / "stale.txt").exists()
    (root / "runs" / "empty").mkdir()
    with pytest.raises(SystemExit, match="nothing published"):
        main(["export-published", str(root / "runs" / "empty")])
