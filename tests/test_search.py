"""Transcript search: the export and api/search.py follow these rules: shows with no_search stay out, one copy of an
episode, at most 2 results per episode and 40 words each, a ticker also finds the company's names, and a result links to the video,
else to Sigma's own page, else to the publisher."""
import importlib.util
import json
import sqlite3
from pathlib import Path

from sigma import library, searchindex

SPEC = importlib.util.spec_from_file_location("api_search", Path(__file__).resolve().parent.parent / "api" / "search.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


def make_index(tmp_path):
    lib = library.connect(tmp_path / "lib.sqlite", write=True)
    # (id, show, title, video): b is a no_search show; e is a's episode again under a second feed (same title and day, no video)
    for eid, show, title, yt in [("a", "Open Show", "Episode a", "https://yt/watch?v=1"), ("b", "Hidden Show", "Episode b", None),
                                 ("c", "Open Show", "Episode c", None), ("d", "Open Show", "Episode d", None),
                                 ("e", "Other Feed", "Episode a", None)]:
        lib.execute("INSERT INTO episodes (episode_id, title, show, published, url, youtube_url, has_transcript) VALUES (?,?,?,?,?,?,1)",
                    (eid, title, show, "2026-10-26", f"https://pod/{eid}", yt))
        text = f"Zetacorp {title.split()[-1]} " + " ".join(f"w{i}" for i in range(300))  # an episode's own words; a's second feed has the same
        for n in range(4):  # four matching passages in every episode
            cur = lib.execute("INSERT INTO chunks (episode_id, ts) VALUES (?,?)", (eid, 100 * n + 5))
            lib.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?,?)", (cur.lastrowid, text))
    lib.commit()
    lib.close()
    (tmp_path / "sources.yaml").write_text("sources:\n  - {id: open, name: Open Show, tier: 1, rss: 'x'}\n"
                                           "  - {id: hid, name: Hidden Show, tier: 1, rss: 'y', no_search: true}\n")
    (tmp_path / "entities.json").write_text(json.dumps({"companies": {"z": {"name": "Zetacorp", "ticker": "ZTC", "aliases": []}}}))
    pub = tmp_path / "published" / "run"
    pub.mkdir(parents=True)
    (pub / "claims.jsonl").write_text(json.dumps({"episode_id": "c"}) + "\n")  # only c has a page on the site
    out = tmp_path / "index.sqlite"
    counts = searchindex.build(tmp_path / "lib.sqlite", out, tmp_path / "published", tmp_path / "sources.yaml", tmp_path / "entities.json")
    return out, counts


def test_export_and_function_follow_the_rules(tmp_path):
    out, counts = make_index(tmp_path)
    assert counts["episodes"] == 3 and counts["no_search"] == 1 and counts["duplicates"] == 1
    res = api.search("zetacorp", str(out))
    assert {r["show"] for r in res} == {"Open Show"}  # the hidden show and the second feed's copy never appear
    assert len(res) == 6 and all([r["title"] for r in res].count(t) == 2 for t in ("Episode a", "Episode c", "Episode d"))
    assert all(len(r["snippet"].split()) <= 40 and "[[Zetacorp]]" in r["snippet"] for r in res)
    link = {r["title"]: r["link"] for r in res}
    assert link["Episode a"].startswith("https://yt/watch?v=1&t=")  # a video: opens at the moment
    assert link["Episode c"] == "/episodes/c.html"  # no video, a page of its own on the request's origin
    assert link["Episode d"] == "https://pod/d"  # neither: the publisher's page
    assert sorted(r["time"] for r in res if r["title"] == "Episode c") == ["0:05", "1:45"]  # the time shown as text
    with sqlite3.connect(out) as con:
        con.execute("UPDATE episodes SET url=? WHERE episode_id=?", ("javascript:alert(1)", "d"))
    unsafe = next(r for r in api.search("zetacorp", str(out)) if r["title"] == "Episode d")
    assert unsafe["link"] is None
    assert api.safe_url("/episodes/c.html") == "/episodes/c.html"
    assert api.safe_url("https://pod.example/episode") == "https://pod.example/episode"
    assert api.safe_url("//evil.example/path") is None and api.safe_url("javascript:alert(1)") is None


def test_a_ticker_finds_the_company_but_only_when_typed_as_one(tmp_path):
    out, _ = make_index(tmp_path)
    assert len(api.search("ZTC", str(out))) == 6 and len(api.search("$ztc", str(out))) == 6
    assert api.search("ztc", str(out)) == []  # lower case is a word, not a ticker
    assert len(api.search("ZTC w7", str(out))) == 6  # another word after the ticker still works


def test_function_reads_the_query_as_the_library_does():
    for q in ['Sam Altman', '"rate cut" fed', "S&P 500", "AT&T-mobility."]:
        assert api.fts_query(q).replace(" AND ", " ") == library.fts_query(q)
