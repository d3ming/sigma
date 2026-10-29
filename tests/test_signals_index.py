"""The Signals index (sigma signals-index): rules from docs/PRODUCT-DIRECTION.md, stated in schema/signals-index.schema.json."""


def test_the_index_never_waits_names_what_is_missing_and_every_published_file_is_valid(tmp_path, monkeypatch):
    """stated-rule (PRODUCT-DIRECTION: the index never waits, it writes complete:false and names the source); outside-value
    for the post time: an X post id carries its time (snowflake, ms since 2010-11-04 01:42:54.657 UTC), and the scan
    fixture of test_xdaily gives this id the minute 13:08Z on 2026-10-26. Failure-seen: publication preflight rejected
    Pacific stance dates as UTC dates; 03:10 UTC on Oct 27 is 20:10 PDT on Oct 26, worked by hand."""
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
    labels = pub / "x" / "stances" / f"{day}.jsonl"
    labels.parent.mkdir(parents=True)
    row = {"key": f"p-{post_id}", "id": post_id, "handle": "reader", "date": day,
           "labels": [{"ticker": "NVDA", "stance": 2, "reason": "Expects stronger demand"}]}
    labels.write_text(json.dumps(row) + "\n")
    monkeypatch.setenv("SIGMA_DATA_ROOT", str(data))
    monkeypatch.setenv("SIGMA_X_DIR", str(data / "x"))
    monkeypatch.setattr(signals_index, "DATA", data)
    now = datetime.fromisoformat("2026-10-27T06:00:00+00:00")
    day_file = pub / "signals" / f"{day}.json"
    day_file.parent.mkdir()
    day_file.write_text(json.dumps(signals_index.build(day, pub, now=now)))
    frozen = tmp_path / "frozen"
    published.freeze_publication_inputs(data, frozen)
    accepted = (frozen / "published" / "signals" / day_file.name).read_bytes()
    assert accepted == day_file.read_bytes()
    assert json.loads(accepted)["signals"][0]["date"] == "2026-10-26"
    row["date"] = "2026-10-27"
    labels.write_text(json.dumps(row) + "\n")
    day_file.write_text(json.dumps(signals_index.build(day, pub, now=now)))
    with pytest.raises(ValueError, match="X stance source mismatch"):
        published.freeze_publication_inputs(data, tmp_path / "refused")
    assert (frozen / "published" / "signals" / day_file.name).read_bytes() == accepted
