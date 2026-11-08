"""The 2026-11-07 data loss: runs scored on the old Mac sat in runs/ without a published copy for two weeks, and nothing
said so. A publication now refuses that, and refuses a build missing an episode the site serves."""
import json

from sigma import coverage


def scored_run(root, name, published, episodes=()):
    (root / "runs" / name).mkdir(parents=True)
    (root / "runs" / name / "ranked.json").write_text(json.dumps({"episodes": [{"episode_id": e, "score": 7} for e in episodes]}))
    if published:
        (root / "published" / name).mkdir(parents=True)


def build(tmp_path, episodes, social=(), merged=None, name="build"):
    static = tmp_path / name
    (static / "social").mkdir(parents=True)
    (static / "episodes.json").write_text(json.dumps({"episodes": list(episodes), "merged": merged or {}}))
    (static / "social" / "episodes.json").write_text(json.dumps({"episodes": list(social)}))
    return static


def live(monkeypatch, *episodes):
    monkeypatch.setattr(coverage, "live_lists", lambda url: {"episodes": {e["episode_id"]: e for e in episodes}, "merged": {}})


def test_a_scored_run_without_a_published_copy_or_a_dropped_live_episode_refuses(tmp_path, monkeypatch):
    scored_run(tmp_path, "2026-10-17-weekly", published=False)
    scored_run(tmp_path, "2026-11-07-weekly", published=True)
    (tmp_path / "runs" / "2026-11-08-unranked").mkdir()
    static = build(tmp_path, [{"episode_id": "rss:a"}])
    live(monkeypatch, {"episode_id": "rss:a"}, {"episode_id": "rss:b"})
    problems, _ = coverage.check(tmp_path, static, "https://sigma.example")
    assert len(problems) == 2 and "rss:b" in problems[0] and "2026-10-17-weekly" in problems[1]
    assert "2026-11-07-weekly" not in problems[1] and "2026-11-08-unranked" not in problems[1]
    (tmp_path / "withheld.json").write_text(json.dumps({"episodes": {"rss:b": "taken down at the source"},
                                                        "runs": {"2026-10-17-weekly": "speaker labels unverifiable"}}))
    assert coverage.check(tmp_path, static, "https://sigma.example")[0] == []


def test_an_id_the_build_merged_into_the_same_release_is_not_a_dropped_episode(tmp_path, monkeypatch):
    """stated-rule: the site redirects a merged-away id's pages, so publishing the merge must not read as data loss; a merge into
    a different release (rss:b, a week later) is a drop."""
    show = {"show": "Latent Space"}
    static = build(tmp_path, [{"episode_id": "yt:P735f1xlpL0", "published": "2026-11-06", **show}],
                   merged={"rss:a": "yt:P735f1xlpL0", "rss:b": "yt:P735f1xlpL0", "rss:c": "yt:gone"})
    live(monkeypatch, {"episode_id": "yt:P735f1xlpL0", "published": "2026-11-06", **show},
         {"episode_id": "rss:a", "published": "2026-11-06T09:00:00+00:00", "youtube_url": "https://www.youtube.com/watch?v=P735f1xlpL0", **show},
         {"episode_id": "rss:b", "published": "2026-11-13", **show}, {"episode_id": "rss:c", "published": "2026-11-06", **show})
    problems, _ = coverage.check(tmp_path, static, "https://sigma.example")
    assert len(problems) == 1 and "rss:b" in problems[0] and "rss:c" in problems[0] and "rss:a" not in problems[0]


def test_a_social_episode_the_build_lists_nowhere_refuses_and_one_moved_to_the_main_list_does_not(tmp_path, monkeypatch):
    """failure-seen (review of 2026-11-07, a copy of the real data root): a show flipped from influencer to interview took its
    live Social episodes off both lists, and only the main list was checked."""
    deployed = build(tmp_path, [], social=[{"episode_id": "yt:kept"}, {"episode_id": "yt:moved"}, {"episode_id": "yt:gone"}], name="deployed")
    static = build(tmp_path, [{"episode_id": "yt:moved"}], social=[{"episode_id": "yt:kept"}])
    monkeypatch.setattr(coverage, "live_lists", lambda url: None)
    problems, _ = coverage.check(tmp_path, static, "https://sigma.example", previous=deployed)
    assert len(problems) == 1 and "yt:gone" in problems[0] and "yt:moved" not in problems[0] and "yt:kept" not in problems[0]


def test_a_published_run_whose_scored_episodes_are_not_in_the_build_refuses(tmp_path, monkeypatch):
    """failure-seen (review of 2026-11-07, a copy of the real data root): published/<run> with no ranked.json and an empty
    claims.jsonl is skipped by the site, its episodes vanish, and a check for the folder alone passed."""
    scored_run(tmp_path, "2026-10-25-latent-space", published=True, episodes=["rss:x", "rss:y"])
    static = build(tmp_path, [{"episode_id": "rss:x"}])
    live(monkeypatch)
    problems, _ = coverage.check(tmp_path, static, "https://sigma.example")
    assert len(problems) == 1 and "rss:y" in problems[0] and "rss:x" not in problems[0]


def test_a_social_score_the_site_would_list_but_the_build_lacks_refuses(tmp_path, monkeypatch):
    """failure-seen (second review of 2026-11-07, a copy of the real data root): published/2026-11-07-weekly without its
    scores-influencer.json lost 17 Social episodes and the guard passed. Below the floor (MIN_SCORE 4) or without claims the
    site lists none, so those are not expected."""
    scored_run(tmp_path, "2026-11-07-weekly", published=True)
    (tmp_path / "runs" / "2026-11-07-weekly" / "scores-influencer.json").write_text(json.dumps({"episodes": [
        {"episode_id": "yt:floor", "score": 4, "claims": [{"claim": "c"}]}, {"episode_id": "yt:low", "score": 3, "claims": [{"claim": "c"}]},
        {"episode_id": "yt:bare", "score": 6, "claims": []}]}))
    live(monkeypatch)
    problems, _ = coverage.check(tmp_path, build(tmp_path, []), "https://sigma.example")
    assert len(problems) == 1 and "yt:floor" in problems[0] and "yt:low" not in problems[0] and "yt:bare" not in problems[0]


def test_a_social_episode_is_expected_by_the_score_the_site_keeps_not_by_any_run_score(tmp_path, monkeypatch):
    """failure-seen (final review of 2026-11-07, a copy of the real data root): an episode scored 3 first and 6 later is shown
    with its first score, so the site leaves it off Social, and the guard refused the publish. A score only reused (scored_in
    names a run that lacks it) has no run that shows it, so the site loses it and the guard must still refuse."""
    def social(run, *episodes):
        scored_run(tmp_path, run, published=True)
        (tmp_path / "runs" / run / "scores-influencer.json").write_text(json.dumps({"episodes": [
            {"episode_id": eid, "score": score, "scored_in": made_in, "claims": [{"claim": "c"}]} for eid, score, made_in in episodes]}))

    social("2026-10-28", ("yt:rescored", 3, None))
    social("2026-10-29-videos", ("yt:rescored", 6, None))
    social("2026-10-30", ("yt:rescored", 6, "2026-10-29-videos"), ("yt:orphan", 7, "2026-10-29-videos"))
    live(monkeypatch)
    problems, _ = coverage.check(tmp_path, build(tmp_path, []), "https://sigma.example")
    assert len(problems) == 1 and "run 2026-10-30" in problems[0] and "yt:orphan" in problems[0] and "yt:rescored" not in problems[0]


def test_a_served_episode_that_keeps_its_id_but_loses_its_page_or_every_claim_refuses(tmp_path, monkeypatch):
    """failure-seen (second review of 2026-11-07, a copy of the real data root): emptying published/2026-11-02-weekly's
    claims.jsonl kept every id but took 29 episode pages and 154 claims off the site, and the guard passed."""
    page = "https://sigma.example/episodes/x.html"
    live(monkeypatch, {"episode_id": "rss:paged", "page": page, "claims": 5}, {"episode_id": "rss:claims", "page": page, "claims": 3},
         {"episode_id": "rss:fewer", "page": page, "claims": 6})
    static = build(tmp_path, [{"episode_id": "rss:paged", "page": None, "claims": 5}, {"episode_id": "rss:claims", "page": page, "claims": 0},
                              {"episode_id": "rss:fewer", "page": page, "claims": 2}])
    problems, _ = coverage.check(tmp_path, static, "https://sigma.example")
    assert len(problems) == 1 and "rss:paged" in problems[0] and "rss:claims" in problems[0] and "rss:fewer" not in problems[0]
