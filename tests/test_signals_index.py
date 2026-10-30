"""The Signals index (sigma signals-index): rules from docs/PRODUCT-DIRECTION.md, stated in schema/signals-index.schema.json."""


def test_the_index_never_waits_names_what_is_missing_and_every_published_file_is_valid(tmp_path, monkeypatch):
    """stated-rule (PRODUCT-DIRECTION: the index never waits, it writes complete:false and names the source); outside-value
    for the post time: an X post id carries its time (snowflake, ms since 2010-11-04 01:42:54.657 UTC), and the scan
    fixture of test_xdaily gives this id the minute 13:08Z on 2026-10-26. Failure-seen: publication preflight rejected
    Pacific stance dates as UTC dates; 03:10 UTC on Oct 27 is 20:10 PDT on Oct 26, worked by hand. A standalone X
    stance file also reached Sentiment/creator views without its scan in the frozen publication snapshot."""
    import json
    from datetime import datetime

    import pytest

    from sigma import published, signals_index

    assert signals_index.post_time("2114705686513033360")[:16] == "2026-10-26T06:08"  # 13:08Z, Pacific
    wed, sun = "2026-10-28", "2026-10-25"
    doc = signals_index.build(wed, tmp_path, us={})
    assert (doc["complete"], [m["source"] for m in doc["missing"]], doc["signals"]) == (False, ["podcast", "x"], [])
    assert [m["source"] for m in signals_index.build(sun, tmp_path, us={})["missing"]] == ["x"]  # no daily issue on a weekend
    assert signals_index.check(doc, tmp_path) == []

    data, day = tmp_path / "data", "2026-10-26"
    pub, scan = data / "published", data / "x" / "scan" / day
    scan.mkdir(parents=True)
    post_id = "2114917500318646272"
    post = {"id": post_id, "handle": "reader", "created_at": "2026-10-27T03:10:00Z", "text": "Expects NVDA demand to rise", "cashtags": ["NVDA"]}
    (scan / "manifest.json").write_text("{}")
    (scan / "posts.jsonl").write_text(json.dumps(post) + "\n")
    (scan / "quoted.jsonl").write_text("")
    claim = {"episode_id": "rss:four", "timestamp": 60, "text": "Expects NVDA demand to rise", "score": 4,
             "source": "ranked", "date": day, "speaker": "Jane Doe", "title": "Jane Doe on NVDA", "show": "Market Hour",
             "link": "https://example.com/episode?t=60"}
    creator_claim = {**claim, "episode_id": "yt:creator9", "text": "Amazon creator expects demand to rise", "score": None,
                     "date": "2026-10-30", "published": "2026-10-30T01:02:32+00:00", "speaker": "Creator",
                     "title": "Creator on Amazon", "link": "https://youtube.com/watch?v=creator9&t=60"}
    low_creator_claim = {**creator_claim, "episode_id": "yt:creator3", "text": "Below the creator rating floor"}
    score_four_pub = tmp_path / "score-four-published"
    run = score_four_pub / day
    run.mkdir(parents=True)
    low_claim = {**claim, "episode_id": "rss:three", "score": 3, "text": "Below the feed rating floor"}
    (run / "claims.jsonl").write_text("".join(json.dumps(c) + "\n" for c in (claim, low_claim)))
    from sigma import stance
    labels = [{"key": stance.claim_key(c["episode_id"], c["timestamp"], c["text"]), "labels": [
        {"ticker": "NVDA", "stance": 1, "reason": "Expects stronger demand"}
    ]} for c in (claim, low_claim)]
    (run / "stances.jsonl").write_text("".join(json.dumps(row) + "\n" for row in labels))
    video_run = score_four_pub / f"{day}-videos"
    video_run.mkdir()
    (video_run / "claims.jsonl").write_text("".join(json.dumps(c) + "\n" for c in (creator_claim, low_creator_claim)))
    (video_run / "scores-influencer.json").write_text(json.dumps({"episodes": [
        {"episode_id": "yt:creator9", "score": 9}, {"episode_id": "yt:creator3", "score": 3}
    ]}))
    creator_labels = [{"key": stance.claim_key(c["episode_id"], c["timestamp"], c["text"]), "labels": [
        {"ticker": "AMZN", "stance": 1, "reason": "Demand rising"}
    ]} for c in (creator_claim, low_creator_claim)]
    (video_run / "stances.jsonl").write_text("".join(json.dumps(row) + "\n" for row in creator_labels))
    labels = pub / "x" / "stances" / f"{day}.jsonl"
    labels.parent.mkdir(parents=True)
    row = {"key": f"p-{post_id}", "id": post_id, "handle": "reader", "date": day,
           "labels": [{"ticker": "NVDA", "stance": 2, "reason": "Expects stronger demand"}]}
    labels.write_text(json.dumps(row) + "\n")
    standalone_day, standalone_event_day = "2026-10-27", "2026-10-26"
    standalone_scan = data / "x" / "scan" / standalone_day
    standalone_scan.mkdir(parents=True)
    standalone_id = "2115000000000000000"
    standalone_post = {**post, "id": standalone_id, "created_at": "2026-10-27T03:10:00Z"}
    standalone_child_id, unrelated_id = "2115000001000000000", "2115000002000000000"
    standalone_child = {**standalone_post, "id": standalone_child_id, "created_at": "2026-10-27T03:11:00Z",
                        "in_reply_to_id": standalone_id, "in_reply_to_handle": "reader", "conversation_id": "thread-1"}
    standalone_post["conversation_id"] = "thread-1"
    unrelated_post = {**standalone_post, "id": unrelated_id, "handle": "other", "conversation_id": "other-thread"}
    (standalone_scan / "manifest.json").write_text("{}")
    standalone_posts = [standalone_post, standalone_child, unrelated_post]
    (standalone_scan / "posts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in standalone_posts))
    (standalone_scan / "quoted.jsonl").write_text("")
    standalone = {"key": f"p-{standalone_id}", "id": standalone_id, "handle": "reader", "date": standalone_event_day,
                  "thread": [standalone_child_id],
                  "labels": [{"ticker": "NVDA", "stance": 1, "reason": "Expects continued demand"}]}
    standalone_file = pub / "x" / "stances" / f"{standalone_day}.jsonl"
    standalone_file.write_text(json.dumps(standalone) + "\n")
    monkeypatch.setenv("SIGMA_DATA_ROOT", str(data))
    monkeypatch.setenv("SIGMA_X_DIR", str(data / "x"))
    monkeypatch.setattr(signals_index, "DATA", data)
    now = datetime.fromisoformat("2026-10-27T06:00:00+00:00")
    doc = signals_index.build(day, score_four_pub, {"NVDA": "NVIDIA", "AMZN": "Amazon"}, now=now)
    signals = doc["signals"]
    assert any(s["source_kind"] == "podcast" and s["source_id"] == "rss:four" for s in signals)
    assert not any(s["source_id"] == "rss:three" for s in signals)
    assert any(s["source_kind"] == "youtube" and s["source_id"] == "yt:creator9" for s in signals)
    creator_signal = next(s for s in signals if s["source_id"] == "yt:creator9")
    assert creator_signal["date"] == "2026-10-29" and creator_signal["ticker"] == "AMZN"
    assert not any(s["source_id"] == "yt:creator3" for s in signals)
    day_file = pub / "signals" / f"{day}.json"
    day_file.parent.mkdir()
    day_file.write_text(json.dumps(signals_index.build(day, pub, now=now)))
    frozen = tmp_path / "frozen"
    published.freeze_publication_inputs(data, frozen)
    accepted = (frozen / "published" / "signals" / day_file.name).read_bytes()
    assert accepted == day_file.read_bytes()
    assert json.loads(accepted)["signals"][0]["date"] == "2026-10-26"
    assert (frozen / "x" / "scan" / standalone_day / "posts.jsonl").read_bytes() == (standalone_scan / "posts.jsonl").read_bytes()
    assert standalone_day != standalone["date"]

    standalone_bytes = standalone_file.read_bytes()
    standalone_file.write_text(json.dumps({**standalone, "thread": [standalone_child_id, unrelated_id]}) + "\n")
    with pytest.raises(ValueError, match="X stance source mismatch"):
        published.freeze_publication_inputs(data, tmp_path / "bad-thread")
    standalone_file.write_bytes(standalone_bytes)

    bundled_file = pub / "x" / "stances" / "bundle.jsonl"
    bundled_file.write_text(json.dumps(standalone) + "\n")
    with pytest.raises(ValueError, match="X stance has invalid source filename"):
        published.freeze_publication_inputs(data, tmp_path / "invalid-filename")
    bundled_file.unlink()

    missing_day = "2026-10-28"
    missing = {**standalone, "key": "p-2115080000000000000", "id": "2115080000000000000", "date": standalone_event_day}
    missing_file = pub / "x" / "stances" / f"{missing_day}.jsonl"
    missing_file.write_text(json.dumps(missing) + "\n")
    with pytest.raises(ValueError, match=f"X source missing for {missing_day}"):
        published.freeze_publication_inputs(data, tmp_path / "missing-source")
    missing_file.unlink()

    source_posts = (standalone_scan / "posts.jsonl").read_bytes()
    tampered_post = {**standalone_post, "handle": "different"}
    (standalone_scan / "posts.jsonl").write_text(json.dumps(tampered_post) + "\n")
    with pytest.raises(ValueError, match="X stance source mismatch"):
        published.freeze_publication_inputs(data, tmp_path / "bad-source")
    assert (frozen / "x" / "scan" / standalone_day / "posts.jsonl").read_bytes() == source_posts
    (standalone_scan / "posts.jsonl").write_bytes(source_posts)
    assert (standalone_scan / "posts.jsonl").read_bytes() == source_posts
    assert (frozen / "published" / "signals" / day_file.name).read_bytes() == accepted
