import io
import json
from pathlib import Path

import jsonschema
import pytest

from sigma import library
from sigma.cli import main

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schema" / "library-claim.schema.json").read_text())


def validator(defn=None):
    s = {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], **({"$ref": f"#/$defs/{defn}"} if defn else
                                                                  {"type": "array", "items": {"$ref": "#/$defs/claim"}})}
    return jsonschema.Draft202012Validator(s)


TRANSCRIPT = """---\nepisode_id: ep1\n---\n\n# T\n\n## Transcript\n\n""" + "\n".join(
    f"[0:{m:02d}:{s:02d}] " + ("We are betting on hybrid bonding for HBM stacks" if (m, s) == (1, 10) else f"filler talk number {m}{s}")
    for m in range(0, 3) for s in range(0, 60, 10)) + "\n"


def make_run(root: Path, name="2026-10-20", claim="Nvidia HBM supply is sold out through 2027.") -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "ep1.md").write_text(TRANSCRIPT)
    (run / "ep2.md").write_text("## Transcript\n\n[0:00:05] Amazon Trainium demand is rising.\n")
    (run / "manifest.json").write_text(json.dumps({"run_at": "2026-10-20T10:00:00", "episodes": [
        {"episode_id": "ep1", "file": "ep1.md", "title": "Jensen Huang on HBM", "source": "Show A", "tier": 1,
         "published": "2026-10-19", "url": "https://a.example/ep1", "youtube_id": "abc123", "has_transcript": True,
         "fallback_text": False, "transcript_source": "podcast:transcript", "transcript_url": "https://a.example/ep1.vtt"},
        {"episode_id": "ep2", "file": "ep2.md", "title": "Trainium demand", "source": "Show B", "tier": 2,
         "published": "2026-10-10", "url": "https://b.example/ep2", "has_transcript": True}]}))
    (run / "ranked.json").write_text(json.dumps({"week_of": "2026-10-19", "run_dir": str(run), "ranked_by": "t", "episodes": [
        {"rank": 1, "episode_id": "ep1", "title": "Jensen Huang on HBM", "url": "https://a.example/ep1", "source": "Show A",
         "tier": 1, "published": "2026-10-19", "score": 8, "reason": "r",
         "claims": [{"ticker": ["nvda", "private:Foo"], "claim": claim, "speaker": "Jensen Huang", "timestamp": 70,
                     "novelty": 2, "verifiable": 3}]},
        {"rank": 2, "episode_id": "ep2", "title": "Trainium demand", "url": "https://b.example/ep2", "source": "Show B",
         "tier": 2, "published": "2026-10-10", "score": 3, "reason": "r",
         "claims": [{"ticker": ["AMZN"], "claim": "Amazon Trainium demand is rising.", "speaker": "Andy Jassy", "timestamp": 5,
                     "novelty": 1, "verifiable": 1}]}]}))
    (run / "report.json").write_text(json.dumps({"date": "2026-10-20", "title": "t", "run_dir": str(run),
        "key_insights": ["One.", "Two.", "Three."], "essential": [
            {"episode_id": "ep1", "headline": "Jensen on HBM", "show": "Show A", "guests": "Jensen Huang"}], "episodes": [
        {"episode_id": "ep1", "headline": "Jensen on HBM", "url": "https://a.example/ep1",
         "youtube_url": "https://www.youtube.com/watch?v=abc123",
         "signal": [{"text": "Oracle capex doubles next year.", "speaker": "Jensen Huang", "timestamp": 30},
                    {"text": "Oracle capex doubles next year.", "speaker": "Jensen Huang", "timestamp": 30},
                    {"text": "Oracle capex doubles next year.", "speaker": "Jensen Huang", "timestamp": 30}],
         "sections": [{"title": "s", "body": "b", "claims": [{"text": "Oracle capex doubles next year.", "speaker": "Jensen Huang", "timestamp": 30},
                                                              {"text": "Unknown timing remark.", "speaker": "unknown", "timestamp": 70}]}]}]}))
    return run


@pytest.fixture
def lib(tmp_path, capsys):
    """Drive `sigma library ...` on a throwaway database: lib("query", "--ticker", "NVDA") returns the parsed rows."""
    db = str(tmp_path / "lib.sqlite")

    def run(*argv, text=False):
        capsys.readouterr()
        main(["library", argv[0], *argv[1:], "--db", db, *(["--json"] if argv[0] == "query" else [])])
        out = capsys.readouterr().out
        return out if text else json.loads(out)

    run.db = db
    return run


def test_ingest_is_idempotent_replaces_changed_claims_and_leaves_the_run_alone(tmp_path, lib, capsys):
    run = make_run(tmp_path / "runs")
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["episodes"][0]["published"] = "2026-10-30T01:02:32+00:00"
    (run / "manifest.json").write_text(json.dumps(manifest))
    ranked = json.loads((run / "ranked.json").read_text())
    ranked["episodes"][0]["published"] = "2026-10-30T01:02:32+00:00"
    (run / "ranked.json").write_text(json.dumps(ranked))
    before_files = {p.name: p.stat().st_mtime_ns for p in run.iterdir()}
    main(["library", "ingest", str(run), "--no-transcripts", "--db", lib.db])
    assert "2 episodes, 4 claims" in capsys.readouterr().out
    first = lib("stats")
    assert first["episodes"] == 2 and first["claims"] == 4
    boundary_claim = lib("query", "--text", "sold out")[0]
    assert (boundary_claim["published"], boundary_claim["date"]) == ("2026-10-29", "2026-10-29")
    main(["library", "ingest", str(run), "--no-transcripts", "--db", lib.db])
    assert lib("stats") == first  # the same run twice changes nothing
    ranked = json.loads((run / "ranked.json").read_text())
    ranked["episodes"][0]["claims"][0]["claim"] = "Rubin ramps in Q3."
    (run / "ranked.json").write_text(json.dumps(ranked))
    before_files["ranked.json"] = (run / "ranked.json").stat().st_mtime_ns
    main(["library", "ingest", str(run), "--no-transcripts", "--db", lib.db])
    assert lib("query", "--text", "Rubin") and not lib("query", "--text", "sold out")  # replaced, not appended
    assert {p.name: p.stat().st_mtime_ns for p in run.iterdir()} == before_files
    fresh = str(tmp_path / "claims-only.sqlite")
    main(["library", "ingest", str(run), "--db", fresh, "--no-transcripts"])  # claims only: the transcript index stays empty
    capsys.readouterr()
    main(["library", "stats", "--db", fresh])
    assert json.loads(capsys.readouterr().out)["transcript_chunks"] == 0


def test_query_by_ticker_person_date_show_and_text(tmp_path, lib):
    main(["library", "ingest", str(make_run(tmp_path / "runs")), "--no-transcripts", "--db", lib.db])
    nv = lib("query", "--ticker", "NVDA")
    assert [c["speaker"] for c in nv] == ["Jensen Huang"] and nv[0]["tickers"] == ["NVDA", "private:Foo"]
    assert [(c["source"], c["matched_by"]) for c in nv] == [("ranked", "tag")]
    assert [c["text"] for c in lib("query", "--ticker", "private:foo")] == [nv[0]["text"]]
    ids = lambda *a: {c["episode_id"] for c in lib("query", *a)}  # noqa: E731
    assert ids("--person", "Jensen") == {"ep1"}  # speaker or title
    assert ids("--since", "2026-10-15") == {"ep1"} and ids("--until", "2026-10-15") == {"ep2"} and ids("--show", "show b") == {"ep2"}
    assert len(lib("query", "--limit", "2")) == 2
    assert lib("query", "--text", "oracle")[0]["source"] == "report"
    assert lib("query", "--ticker", "ORCL") == [] and lib("query", "--ticker", "Oracle") == []  # company names are not tickers
    assert lib("query", "--text", 'AND OR "unterminated NEAR(') == []  # FTS syntax in the text is not an error
    assert lib("query")[0]["matched_by"] is None
    c = lib("query", "--text", "HBM")[0]
    assert c["link"] == "https://www.youtube.com/watch?v=abc123&t=70s"
    assert c["transcript_url"] == "https://a.example/ep1.vtt" and c["transcript_path"].endswith("ep1.md")
    assert lib("query", "--person", "Jassy")[0]["link"] == "https://b.example/ep2"
    validator().validate(lib("query", "--limit", "0"))


def test_a_ticker_found_in_untagged_text_must_look_like_a_ticker(tmp_path, lib):
    """Claims with no ticker tags are searched by text: the symbol must stand alone, short ones need a $."""
    main(["library", "ingest", str(make_run(tmp_path / "runs")), "--no-transcripts", "--db", lib.db])
    con = library.connect(lib.db, write=True)
    with con:
        for t in ("Right now demand is strong.", "Input costs fell.", "AI spend is up; NOW is a winner.", "Bought $NOW and $AI.",
                  "Costco beat. COST guidance is raised.", "NVDA and AMD both rallied."):
            con.execute("INSERT INTO claims(episode_id, run, run_date, date, source, text) VALUES ('ep1','x','2026-10-20','2026-10-20','report',?)", (t,))
    con.close()
    texts = lambda sym: sorted(c["text"] for c in lib("query", "--ticker", sym, "--limit", "0") if c["matched_by"] == "text")  # noqa: E731
    assert texts("NOW") == ["AI spend is up; NOW is a winner."]  # not "Right now", and bare NOW does not match $NOW
    assert texts("COST") == ["Costco beat. COST guidance is raised."]  # not "Input costs"
    assert texts("AI") == []  # 2-character symbols never match bare text
    assert texts("$AI") == ["Bought $NOW and $AI."] and texts("$NOW") == ["Bought $NOW and $AI."]
    assert texts("NVDA") == ["NVDA and AMD both rallied."]


def test_transcript_search_export_and_two_runs(tmp_path, lib, capsys):
    root = tmp_path / "runs"
    make_run(root, "2026-10-20")
    make_run(root, "2026-10-21", claim="Different claim.")
    main(["library", "ingest", "--all", "--runs", str(root), "--db", lib.db])
    assert lib("stats")["runs"] == ["2026-10-20", "2026-10-21"]
    assert len(lib("query", "--ticker", "AMZN")) == 2
    hits = lib("query", "--transcripts", "--text", "hybrid bonding")
    assert len(hits) == 1  # the same episode in two runs is one passage, not two
    hit = hits[0]
    assert hit["episode_id"] == "ep1" and "**hybrid**" in hit["snippet"] and hit["timestamp"] == 60 and hit["link"].endswith("&t=60s")
    validator("transcript_hit").validate(hit)
    assert lib("query", "--transcripts", "--text", '"bonding hybrid"') == []
    assert lib("query", "--transcripts", "--text", "hybrid", "--since", "2026-10-25") == []
    with pytest.raises(SystemExit, match="library"):
        lib("query", "--transcripts", "--text", "!!!")
    with pytest.raises(SystemExit, match="--transcripts needs --text"):
        lib("query", "--transcripts")
    out_file = tmp_path / "feed.jsonl"
    main(["library", "export", "--out", str(out_file), "--db", lib.db])
    rows = [json.loads(line) for line in out_file.read_text().splitlines()]
    assert len(rows) == 8
    validator().validate(rows)
    capsys.readouterr()
    main(["library", "export", "--since", "2026-10-15", "--db", lib.db])
    assert len(capsys.readouterr().out.splitlines()) == 6  # ep2 was published on 10-10


def test_a_later_run_without_a_transcript_keeps_what_an_earlier_run_found(tmp_path, lib):
    root = tmp_path / "runs"
    main(["library", "ingest", str(make_run(root, "2026-10-20")), "--db", lib.db])
    w = root / "2026-10-27"  # lists ep1 without a transcript, link, tier or score
    w.mkdir()
    (w / "manifest.json").write_text(json.dumps({"run_at": "2026-10-27T10:00:00", "episodes": [
        {"episode_id": "ep1", "file": "ep1.md", "title": "Jensen Huang on HBM", "source": "Show A", "has_transcript": False}]}))
    main(["library", "ingest", str(w), "--db", lib.db])
    assert lib("query", "--transcripts", "--text", '"hybrid bonding"')
    con = library.connect(lib.db)
    row = con.execute("SELECT * FROM episodes WHERE episode_id='ep1'").fetchone()
    con.close()
    assert row["has_transcript"] == 1 and row["transcript_path"].endswith("ep1.md")
    assert row["youtube_url"].endswith("abc123") and row["url"] == "https://a.example/ep1" and row["tier"] == 1 and row["score"] == 8
    before = lib("stats")
    main(["library", "ingest", str(w), "--db", lib.db])  # re-ingest in either order stays idempotent and still preserves
    main(["library", "ingest", str(root / "2026-10-20"), "--db", lib.db])
    after = lib("stats")
    assert before["transcript_chunks"] == after["transcript_chunks"] and before["episodes"] == after["episodes"]
    assert lib("query", "--text", "HBM")[0]["youtube_url"].endswith("abc123")


def test_reading_while_an_ingest_holds_the_write_lock_and_a_missing_library(tmp_path, lib):
    import sqlite3

    with pytest.raises(SystemExit, match="no library at"):
        lib("query")
    assert not (tmp_path / "lib.sqlite").exists()
    main(["library", "ingest", str(make_run(tmp_path / "runs")), "--no-transcripts", "--db", lib.db])
    writer = sqlite3.connect(lib.db, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO claims(episode_id, run, source, text) VALUES ('ep1','y','report','pending')")
    try:
        assert lib("query", "--text", "HBM") and lib("stats")["claims"] >= 3
        assert len(lib("export", text=True).splitlines()) >= 3
    finally:
        writer.execute("ROLLBACK")
        writer.close()
