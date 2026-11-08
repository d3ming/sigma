"""The 2026-11-07 data loss: runs scored on the old Mac sat in runs/ without a published copy for two weeks, and nothing
said so. A publication now refuses that, and refuses a build missing an episode the live site serves."""
import json

from sigma import coverage


def scored_run(root, name, published):
    (root / "runs" / name).mkdir(parents=True)
    (root / "runs" / name / "ranked.json").write_text("{}")
    if published:
        (root / "published" / name).mkdir(parents=True)


def test_a_scored_run_without_a_published_copy_or_a_dropped_live_episode_refuses(tmp_path, monkeypatch):
    scored_run(tmp_path, "2026-10-17-weekly", published=False)
    scored_run(tmp_path, "2026-11-07-weekly", published=True)
    (tmp_path / "runs" / "2026-11-08-unranked").mkdir()
    build = tmp_path / "episodes.json"
    build.write_text(json.dumps({"episodes": [{"episode_id": "rss:a"}]}))
    monkeypatch.setattr(coverage, "live_episodes", lambda url: {"rss:a", "rss:b"})
    problems = coverage.check(tmp_path, build, "https://sigma.example")
    assert len(problems) == 2 and "rss:b" in problems[0] and "2026-10-17-weekly" in problems[1]
    assert "2026-11-07-weekly" not in problems[1] and "2026-11-08-unranked" not in problems[1]
    (tmp_path / "withheld.json").write_text(json.dumps({"episodes": {"rss:b": "taken down at the source"},
                                                        "runs": {"2026-10-17-weekly": "speaker labels unverifiable"}}))
    assert coverage.check(tmp_path, build, "https://sigma.example") == []


def test_an_id_the_build_merged_into_another_episode_is_not_a_dropped_episode(tmp_path, monkeypatch):
    """stated-rule: the site redirects a merged-away id's pages, so publishing the merge must not read as data loss."""
    build = tmp_path / "episodes.json"
    build.write_text(json.dumps({"episodes": [{"episode_id": "yt:a"}], "merged": {"rss:a": "yt:a", "rss:b": "yt:gone"}}))
    monkeypatch.setattr(coverage, "live_episodes", lambda url: {"yt:a", "rss:a", "rss:b"})
    problems = coverage.check(tmp_path, build, "https://sigma.example")
    assert len(problems) == 1 and "rss:b" in problems[0] and "rss:a" not in problems[0]
