"""The weekly run as an agent runs it (prompts/weekly.md): rank-prep -> readers -> rank-merge -> themes-check -> publish.

Every step goes through wire.cli.main. The readers (agents) are played by the test, which writes rank/batch-N-out.json
from each batch-N-in.json the way prompts/rank.md says."""
import io
import json
import os
import shutil
from contextlib import redirect_stdout
from datetime import datetime, timezone

import pytest

from wire import library, published
from wire.cli import main
from wire.fetch import write_episode
from wire.ingest import Episode

from tests.helpers import STATUS_SHAPE, sandbox, spoken

RUN = "2026-10-19-weekly"
AD = "this episode is brought to you by acme corp " * 8

# id: (show, tier, reader score, published, filler word, what is said at 5:00, claims as (ticker, claim, speaker))
SAID = {
    "a": "we think demand for accelerators will outrun supply well into next year and beyond for sure",
    "b": "our foundry partner has no spare advanced packaging room until the second half of the year",
    "c": "hyperscalers keep raising spending plans every single quarter and nobody there is blinking at all",
    "d": "the smaller challenger is winning design slots because buyers want a second source of supply",
    "e": "power and cooling are now the real bottleneck for new capacity in every region we looked at",
}
EPISODES = {
    "a": ("Show A", 1, 9, "2026-10-18", "alpha", [("NVDA", "Accelerator demand stays ahead of supply into next year", "Ann Lee"),
                                                  ("AMD", "Buyers are qualifying a second chip supplier", "Ann Lee"),
                                                  ("", "The panel liked the venue", "Pat Moss (host)")]),
    "a2": ("Show A on a second feed", 1, 4, "2026-10-17", "alpha", []),  # the same transcript as a
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
        ep = Episode(id=f"rss:{i}", source_id=show.lower().replace(" ", "-"), source_name=show, tier=tier, title=f"Episode {i}", url=url(i),
                     published_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc))
        rows.append(write_episode(run, ep, spoken(lines, filler=word, every=10), "podcast:transcript"))
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


def test_week_from_transcripts_to_published(week, capsys, monkeypatch):
    run, root = week / "runs" / RUN, week
    (run / "transcribe.queued").write_text(str(os.getpid()))  # scoring now would miss the episodes still in the queue
    d = status(run)
    assert (d["stage"], d["next"]["type"]) == ("rank_prep", "wait")
    (run / "transcribe.queued").unlink()
    assert status(run)["next"]["command"] == f"wire rank-prep {run} --eval 6"  # a weekly also re-scores a blind sample to measure drift
    capsys.readouterr()
    main(["rank-prep", str(run)])
    out = capsys.readouterr().out
    assert "10 of 10 transcribed episodes to score in 4 batches" in out and "1 without a transcript" in out
    batches = [json.loads((run / "rank" / f"batch-{k}-in.json").read_text()) for k in (1, 2, 3, 4)]
    ids = sorted(e["episode_id"] for b in batches for e in b)
    assert ids == sorted(f"rss:{i}" for i in EPISODES) and sorted(len(b) for b in batches) == [2, 2, 3, 3]  # the episode without text is not ranked
    cond = (run / batches[0][0]["file"]).read_text()  # readers cite timestamps from the condensed text: one every 30 s
    assert "[0:05:00]" in cond and "[0:05:10]" not in cond and "[0:05:30]" in cond
    assert len(cond) < len((run / batches[0][0]["file"].replace("rank/cond/", "")).read_text())
    d = status(run)
    assert d["kind"] == "weekly" and d["stage"] == "readers" and d["next"]["prompt"] == "prompts/rank.md"
    read_batches(run)
    (run / "rank" / "batch-4-out.json").unlink()
    d = status(run)
    assert d["stage"] == "readers" and "batch-4-in.json" in d["next"]["summary"]
    read_batches(run)
    assert status(run)["next"]["command"] == f"wire rank-merge {run}"

    # a reader returning an id the manifest does not know stops the merge before ranked.json exists
    edit(run / "rank" / "batch-1-out.json", lambda rows: rows[0].update(episode_id="rss:nope"))
    with pytest.raises(SystemExit, match="rss:nope"):
        main(["rank-merge", str(run)])
    assert not (run / "ranked.json").exists()
    read_batches(run)
    capsys.readouterr()
    main(["rank-merge", str(run)])
    assert "warning: spread: fewer than 30% of episodes score 4 or less" in capsys.readouterr().out  # prompts/rank.md: a soft check
    ranked = json.loads((run / "ranked.json").read_text())
    # prompts/rank.md: best score first, then tier; the same transcript on two feeds counts once (the higher score stays); an ad
    # read that two episodes share does not make them one; at most 2 tier-3 episodes and never in ranks 1-3 (g scores 10)
    assert [e["episode_id"] for e in ranked["episodes"]] == [f"rss:{i}" for i in "abcgdehi"]
    assert [e["rank"] for e in ranked["episodes"]] == list(range(1, 9)) and ranked["week_of"] == "2026-10-15"
    assert "Episode a (second feed)" in ranked["notes"] and "Episode g" in ranked["notes"] and "Episode j" in ranked["notes"] and "1 had no usable transcript" in ranked["notes"]
    assert status(run)["next"]["command"] == f"wire publish {run}/ranked.json --top 15"

    # themes-check and publish: the digest holds the top 5 of 8, each cited claim and theme is grounded
    (run / "themes.json").write_text(json.dumps(themes_json()))
    capsys.readouterr()
    main(["themes-check", str(run), "--top", "5"])
    monkeypatch.setattr(published, "ROOT", root / "published")
    monkeypatch.delenv("PA_NO_PUBLISHED")
    main(["publish", str(run / "ranked.json"), "--top", "5"])
    digest = (run / "digest-2026-10-15.md").read_text()
    assert "Top 5 of 8 ranked episodes" in digest and "## 5. Episode d" in digest and "Episode e" not in digest and "Episode h" not in digest
    assert "[0:05:00](https://www.youtube.com/watch?v=aaaaaaaaaaa&t=300s)" in digest
    # Ann Lee is a guest on a and c; Pat Moss is labelled host in a, so the bare Pat Moss in c and d is not a repeat guest
    assert digest.count("another interview with") == 1 and "Also #1: another interview with Ann Lee" in digest
    pub = root / "published" / RUN
    assert sorted(p.name for p in pub.iterdir()) == ["claims.jsonl", "digest-2026-10-15.md", "episodes.json", "ranked.json", "themes.json"]
    th = json.loads((pub / "themes.json").read_text())
    ev = th["themes"][0]["evidence"][0]
    assert th["themes"][0]["came_up_in"] == {"episodes": 3, "of": 8} and th["themes"][0]["tickers"] == ["NVDA"]
    assert (ev["claim"], ev["speaker"], ev["show"], ev["timestamp"]) == ("Accelerator demand stays ahead of supply into next year", "Ann Lee", "Show A", 300)
    assert ev["link"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa&t=300s" and th["themes"][1]["evidence"][0]["link"] == "https://example.com/b"
    assert status(run)["stage"] == "done"
    assert "transcript" not in " ".join(p.name for p in pub.iterdir()) and "alpha alpha" not in (pub / "claims.jsonl").read_text()


def test_an_episode_is_scored_once_and_a_blind_re_score_never_replaces_it(week, capsys, monkeypatch):
    """prompts/rank.md: the first run to transcribe an episode scores it and the library keeps that score; a later run reads
    only the unscored ones, and re-scoring stored episodes blind is an eval that measures drift. An episode from a
    `style: influencer` source (stated rule) is read under prompts/rank-influencer.md and lands in
    scores-influencer.json, never in the ranking, even with a 10 that would put it first."""
    root, first = week, week / "runs" / RUN
    monkeypatch.delenv("PA_NO_LIBRARY")
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
    # 1 point, and only d crosses the site's bar of 6 (select.md: candidates score 6 or more)
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
    monkeypatch.setattr(published, "ROOT", root / "published")
    monkeypatch.delenv("PA_NO_PUBLISHED")
    ranked = (run / "ranked.json").read_text()
    manifest = (run / "manifest.json").read_text()
    said = SAID["a"]

    def ts(i, n, v):
        return lambda d: ep_row(d, i)["claims"][n].update(timestamp=v)

    cases = {
        "a score of 11": lambda d: ep_row(d, "a").update(score=11),
        "a field outside the schema": lambda d: ep_row(d, "a").update(weight=0.1),
        "ranks that skip": lambda d: ep_row(d, "b").update(rank=5),
        "tier 3 in the top 3": lambda d: ep_row(d, "b").update(tier=3),
        "three tier-3 episodes": lambda d: [ep_row(d, i).update(tier=3) for i in "dh"] and ep_row(d, "e").update(tier=3),
        "holdings in a reason": lambda d: ep_row(d, "a").update(reason="holding 5% of NVDA"),
        "an episode the manifest does not know": lambda d: ep_row(d, "a").update(episode_id="rss:nope"),
        "a timestamp past the end of the transcript": ts("a", 0, 4000),
        "twelve words copied from the transcript": lambda d: ep_row(d, "a")["claims"][0].update(claim=said),
    }
    for why, mutate in cases.items():
        (run / "ranked.json").write_text(ranked)
        edit(run / "ranked.json", mutate)
        with pytest.raises(SystemExit):
            main(["publish", str(run / "ranked.json"), "--top", "5"])
        assert not list(run.glob("digest-*.md")) and not (root / "published").exists(), why
    # claims on an episode whose transcript is only a show description
    (run / "ranked.json").write_text(ranked)
    edit(run / "manifest.json", lambda m: next(e for e in m["episodes"] if e["episode_id"] == "rss:b").update(has_transcript=False))
    with pytest.raises(SystemExit):
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert not list(run.glob("digest-*.md"))
    # eleven copied words are a paraphrase
    (run / "manifest.json").write_text(manifest)
    edit(run / "ranked.json", lambda d: ep_row(d, "a")["claims"][0].update(claim=" ".join(said.split()[:11])))
    main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert list(run.glob("digest-*.md")) and (root / "published" / RUN / "ranked.json").exists()


def test_ranking_without_a_manifest_is_published_with_one_warning(ranked_week, capsys):
    """The claims cannot be grounded without the run's manifest: say so once and still render. An episode with no page
    is listed by title, never as an empty link."""
    run = ranked_week
    (run / "manifest.json").unlink()
    edit(run / "ranked.json", lambda d: ep_row(d, "a").update(url=""))
    capsys.readouterr()
    main(["publish", str(run / "ranked.json"), "--top", "5"])
    warnings = [l for l in capsys.readouterr().out.splitlines() if "warning:" in l and "manifest.json" in l]
    digest, = run.glob("digest-*.md")
    assert len(warnings) == 1 and "| Episode a |" in digest.read_text() and "]()" not in digest.read_text()


THEME_CASES = {
    "week_of that differs from ranked.json": (lambda d: d.update(week_of="2026-10-16"), "differs from ranked.json"),
    "a run name that is not the folder": (lambda d: d.update(run="other-run"), "not this run folder's name"),
    "an episode_ids entry not in ranked.json": (lambda d: d["themes"][0].update(episode_ids=["rss:a", "rss:zzz"]), "rss:zzz is not in ranked.json"),
    "evidence from an unknown episode": (lambda d: d["themes"][0].update(evidence=[{"episode_id": "rss:zzz", "claim_index": 0}, {"episode_id": "rss:b", "claim_index": 0}]), "rss:zzz is not in ranked.json"),
    "a claim_index past the claims": (lambda d: d["themes"][0].update(evidence=[{"episode_id": "rss:a", "claim_index": 5}, {"episode_id": "rss:b", "claim_index": 0}]), "claim_index out of range"),
    "evidence from one show only": (lambda d: d["themes"][0].update(evidence=[{"episode_id": "rss:a", "claim_index": 0}, {"episode_id": "rss:c", "claim_index": 0}], tickers=["TSM"]), "distinct show"),
    "a ticker that is on no cited claim": (lambda d: d["themes"][0].update(tickers=["NVDA", "AMD"]), "are not on any cited claim"),
    "evidence from an episode outside episode_ids": (lambda d: d["themes"][0].update(evidence=[{"episode_id": "rss:a", "claim_index": 0}, {"episode_id": "rss:d", "claim_index": 0}]), "not in this theme's episode_ids"),
    "12 transcript words in a summary": (lambda d: d["themes"][0].update(summary="Both shows agreed that " + " ".join(SAID["a"].split()[:13]) + " and moved on."), "summary: "),
    "12 transcript words in the headline": (lambda d: d.update(headline="Everyone says " + " ".join(SAID["d"].split()[:13]) + "."), "headline: "),
}


def test_themes_check_refuses_what_prompts_themes_md_forbids(ranked_week, capsys):
    run = ranked_week
    with pytest.raises(SystemExit, match="no themes.json"):
        main(["themes-check", str(run)])
    for why, (mutate, msg) in THEME_CASES.items():
        data = themes_json()
        mutate(data)
        (run / "themes.json").write_text(json.dumps(data))
        with pytest.raises(SystemExit) as e:
            main(["themes-check", str(run), "--top", "5"])
        lines = str(e.value).splitlines()
        assert any(msg in l for l in lines) and all(l.startswith("[themes-check] invalid: themes: ") for l in lines), (why, lines)
    # 11 copied words are fine; the top N the digest publishes decides which episodes may be cited; tickers keep the claim's spelling
    ok = themes_json()
    ok["themes"][0]["summary"] = "They said " + " ".join(SAID["b"].split()[:11]) + " so it is tight."
    (run / "themes.json").write_text(json.dumps(ok))
    main(["themes-check", str(run), "--top", "5"])
    with pytest.raises(SystemExit, match="rss:d claims.0.*rank 5, outside the published top 4"):
        main(["themes-check", str(run), "--top", "4"])
    # a cited claim that fails the publish checks invalidates the theme; one nobody cites does not
    (run / "themes.json").write_text(json.dumps(themes_json()))
    ranked = (run / "ranked.json").read_text()
    edit(run / "ranked.json", lambda d: ep_row(d, "b")["claims"][0].update(claim=SAID["b"]))
    with pytest.raises(SystemExit, match=r"rss:b claims\[0\].*copied verbatim"):
        main(["themes-check", str(run), "--top", "5"])
    (run / "ranked.json").write_text(ranked)
    (run / "themes.json").write_text(json.dumps(themes_json()))
    ranked = (run / "ranked.json").read_text()
    edit(run / "ranked.json", lambda d: ep_row(d, "a")["claims"][0].update(timestamp=4000))
    with pytest.raises(SystemExit, match=r"evidence\[0\] \(rss:a claims\[0\]\): the claim fails the publish checks"):
        main(["themes-check", str(run), "--top", "5"])
    (run / "ranked.json").write_text(ranked)
    edit(run / "ranked.json", lambda d: ep_row(d, "a")["claims"][2].update(timestamp=4000))
    main(["themes-check", str(run), "--top", "5"])
    with pytest.raises(SystemExit, match="timestamp"):  # publish itself still refuses the bad claim
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    # evidence on an episode without a real transcript
    (run / "ranked.json").write_text(ranked)
    edit(run / "manifest.json", lambda m: next(e for e in m["episodes"] if e["episode_id"] == "rss:b").update(has_transcript=False))
    with pytest.raises(SystemExit, match="rss:b.*no real transcript"):
        main(["themes-check", str(run), "--top", "5"])
    # without a manifest the grounding checks are skipped with one warning, as for claims
    (run / "manifest.json").unlink()
    capsys.readouterr()
    main(["themes-check", str(run), "--top", "5"])
    assert capsys.readouterr().out.count("warning:") == 1


def test_publish_refuses_invalid_themes_and_writes_nothing(ranked_week, monkeypatch):
    run, root = ranked_week, ranked_week.parent.parent
    monkeypatch.setattr(published, "ROOT", root / "published")
    monkeypatch.delenv("PA_NO_PUBLISHED")
    data = themes_json()
    data["themes"][1]["evidence"][1] = {"episode_id": "rss:c", "claim_index": 4}
    (run / "themes.json").write_text(json.dumps(data))
    with pytest.raises(SystemExit) as e:
        main(["publish", str(run / "ranked.json"), "--top", "5"])
    assert "[publish] invalid: themes: themes[1] 'Foundry timing': evidence[1] (rss:c claims[4])" in str(e.value)
    assert not list(run.glob("digest-*.md")) and not (root / "published").exists()
    # export-published: a good file exports; a later refusal leaves the earlier export alone
    (run / "themes.json").write_text(json.dumps(themes_json()))
    main(["export-published", str(run), "--top", "5"])
    assert (root / "published" / RUN / "themes.json").exists()
    with pytest.raises(SystemExit, match=r"\[published\] invalid: themes: themes\[2\]"):
        main(["export-published", str(run), "--top", "4"])
    assert (root / "published" / RUN / "themes.json").exists()
    # a re-export replaces the folder, so a file dropped from the run does not linger; a run with nothing to publish is refused
    (root / "published" / RUN / "stale.txt").write_text("old")
    main(["export-published", str(run), "--top", "5"])
    assert not (root / "published" / RUN / "stale.txt").exists()
    (root / "runs" / "empty").mkdir()
    with pytest.raises(SystemExit, match="nothing published"):
        main(["export-published", str(root / "runs" / "empty")])
