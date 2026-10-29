"""The Alpha index (wire alpha-index): rules from docs/PRODUCT-DIRECTION.md, stated in schema/alpha-index.schema.json."""


def test_the_index_never_waits_names_what_is_missing_and_every_published_file_is_valid(tmp_path):
    """stated-rule (PRODUCT-DIRECTION: the index never waits, it writes complete:false and names the source); outside-value
    for the post time: an X post id carries its time (snowflake, ms since 2010-11-04 01:42:54.657 UTC), and the scan
    fixture of test_xdaily gives this id the minute 13:08Z on 2026-10-26."""
    from wire import alpha_index

    assert alpha_index.post_time("2114705686513033360")[:16] == "2026-10-26T06:08"  # 13:08Z, Pacific
    wed, sun = "2026-10-28", "2026-10-25"
    doc = alpha_index.build(wed, tmp_path, us={})
    assert (doc["complete"], [m["source"] for m in doc["missing"]], doc["signals"]) == (False, ["podcast", "x"], [])
    assert [m["source"] for m in alpha_index.build(sun, tmp_path, us={})["missing"]] == ["x"]  # no daily issue on a weekend
    assert alpha_index.check(doc, tmp_path) == []
