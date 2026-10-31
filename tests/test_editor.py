import hashlib
import json

import pytest

from sigma import editor, published, site


def test_stated_rule_editorial_fields_are_grounded_separate_and_frozen(tmp_path):
    run = tmp_path / "runs" / "2026-01-01"
    run.mkdir(parents=True)
    source = run / "episode.md"
    source.write_text("## Transcript\n[0:00:00] Guest: A good organization rewards people for finding mistakes and makes it safe to discuss uncertainty before decisions.\n"
                      "[0:05:00] Guest: Demand increased thirty percent because the new process saved time.\n"
                      "[0:10:00] Guest: That concludes the conversation.\n")
    row = {"episode_id": "rss:edit", "file": source.name, "has_transcript": True, "title": "Company conversation",
           "source": "Example show", "tier": 2, "published": "2026-01-01", "url": "https://example.invalid/episode",
           "show_image_url": "https://example.invalid/show.jpg"}
    (run / "manifest.json").write_text(json.dumps({"episodes": [row]}))
    ranked = {"week_of": "2026-01-01", "run_dir": "runs/2026-01-01", "ranked_by": "Editor", "episodes": [
        {key: row[key] for key in ("episode_id", "title", "source", "tier", "published", "url")} | {
            "rank": 1, "score": 7, "reason": "Useful organizational detail.", "claims": []}]}
    ranked_bytes = json.dumps(ranked).encode()
    (run / "ranked.json").write_bytes(ranked_bytes)
    edit = {"episode_id": row["episode_id"], "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "key_insights": [{"title": "Reward correction", "text": "The guest favors incentives that expose errors.",
                              "why_it_matters": "This makes hidden problems easier to resolve.", "speaker": "Guest",
                              "start": 0, "end": 20, "companies": [], "inference": None}],
            "dense_summary": [{"title": "Process and demand", "text": "The guest links the process improvement to demand rising 30%.",
                               "start": 0, "end": 310}]}
    path = run / "editor.json"
    path.write_text(json.dumps({"version": 1, "episodes": [edit]}))
    pub, _ = published.export(run, tmp_path / "published", resolver=lambda rows: {})
    exported = json.loads((pub / "episodes.json").read_text())[0]
    assert exported["key_insights"] == edit["key_insights"] and exported["dense_summary"] == edit["dense_summary"]
    assert exported["show_image_url"] == row["show_image_url"]
    registry = site.build_episodes(site.load_runs(tmp_path / "published"))
    assert registry[row["episode_id"]]["show_image_url"] == row["show_image_url"]
    assert (pub / "ranked.json").read_bytes() == ranked_bytes and not (pub / "claims.jsonl").read_text()
    frozen = tmp_path / "frozen"
    published.freeze_publication_inputs(tmp_path, frozen)
    assert (frozen / "runs" / run.name / source.name).read_bytes() == source.read_bytes()
    assert (frozen / "runs" / run.name / "editor.json").read_bytes() == path.read_bytes()
    prior = (pub / "episodes.json").read_bytes()
    edit["dense_summary"][0]["text"] = "The guest says demand increased 90%."
    path.write_text(json.dumps({"version": 1, "episodes": [edit]}))
    with pytest.raises(ValueError, match="number 90"):
        published.export(run, tmp_path / "published", resolver=lambda rows: {})
    assert (pub / "episodes.json").read_bytes() == prior
    edit["dense_summary"][0]["text"] = "The guest links the process improvement to demand rising 30%."
    edit["key_insights"][0]["inference"] = "A good organization rewards people for finding mistakes and makes it safe to discuss uncertainty before decisions."
    path.write_text(json.dumps({"version": 1, "episodes": [edit]}))
    with pytest.raises(ValueError, match="copied"):
        published.export(run, tmp_path / "published", resolver=lambda rows: {})
    assert (pub / "episodes.json").read_bytes() == prior
    source.write_text(source.read_text() + "\nAdditional source material.\n")
    with pytest.raises(ValueError, match="fingerprint"):
        editor.load(run)


def test_stated_rule_home_insights_and_detail_summary_are_separate():
    insight = {"title": "Useful mechanism", "text": "Homepage insight text", "why_it_matters": "Practical implication",
               "speaker": "Guest", "start": 12, "end": 30, "companies": [], "inference": None}
    section = {"title": "Chronological section", "text": "Dense detail appears only on the episode page.", "start": 0, "end": 60}
    episode = {"id": "rss:edit", "title": "Example episode", "show": "Example show", "date": "2026-01-01",
               "published": "2026-01-01", "url": "https://example.invalid/episode", "page": "/episodes/rss_edit.html",
               "score": 7, "reason": "A useful conversation", "claims": [], "runs": [], "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
               "apple_url": None, "spotify_url": None, "spotify_kind": None, "transcript_url": None,
               "key_insights": [insight], "dense_summary": [section], "editor_source": "whisper (youtube audio)",
               "show_image_url": "https://example.invalid/show.jpg"}
    fragment, detail = site.claims_fragment(episode), site.episode_page(episode)
    assert "Homepage insight text" in fragment and section["text"] not in fragment
    assert "Key insights" in detail and "Dense summary" in detail and section["text"] in detail
    home = site.top_entry(episode, expand=True)
    assert "i.ytimg.com" not in home and episode["show_image_url"] not in home
    unbranded = {**episode, "show_image_url": None, "image_url": "https://example.invalid/episode.jpg"}
    assert 'src="/podcast-placeholder.svg"' in site.top_entry(unbranded, expand=True)
    assert 'src="https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"' in detail and 'src="https://example.invalid/show.jpg"' not in detail
    assert "t=12s" in fragment and "t=0s" in detail
    encoded = site.episode_json(episode)
    assert encoded["key_insights"] == [insight] and encoded["dense_summary"] == [section]
    assert encoded["show_image_url"] == episode["show_image_url"]
    assert "## Key insights" in site.episode_md(episode) and section["text"] in site.episode_md(episode)
    podcast = {**episode, "editor_source": "whisper podcast audio"}
    assert "t=12s" not in site.claims_fragment(podcast) and "t=0s" not in site.episode_page(podcast)
    assert "t=12s" not in site.episode_md(podcast)
