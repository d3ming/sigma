"""Restated claims: one point, said by two passes (the ranking reader, the report's bullets and section claims) in their own
words, shows once. Rules come from the owner's bug report (2026-10-28: one episode listed the same $800-900 billion point three
times at 3:05), not from claimdedupe.py. The fixture is that episode's wording with a placeholder speaker."""
import json
from pathlib import Path

import pytest

from wire import claimdedupe, library, published, site

EP = "rss:example-guest"
G = "Guest Placeholder"
RANKED = "Anthropic's S-1 lists future compute and capital commitments of roughly $800 to $900 billion that are not yet in the income statement."
REPORT = "The S-1 lists future capital and compute commitments of roughly $800 to $900 billion, shown as a footnote and not yet in the income statement."
SHORT = "Future commitments total roughly $800 to $900 billion."


def claim(text, ts, speaker=G, tickers=(), ep=EP, **kw):
    return {"episode_id": ep, "speaker": speaker, "timestamp": ts, "text": text, "tickers": list(tickers), **kw}


def three():
    return [claim(RANKED, 185, tickers=["private:Anthropic"], source="ranked", novelty=1, verifiable=3, score=6),
            claim(REPORT, 185, source="report"), claim(SHORT, 185, source="report")]


def test_three_wordings_of_one_point_at_one_moment_become_the_most_complete_one_with_the_tags():
    kept, merged = claimdedupe.dedupe(three())
    assert [c["text"] for c in kept] == [REPORT]  # the most complete wording
    assert kept[0]["tickers"] == ["private:Anthropic"]  # the tag only the ranking reader gave
    assert (kept[0]["novelty"], kept[0]["verifiable"], kept[0]["score"]) == (1, 3, 6)  # a rating the keeper lacks comes from the group
    assert [len(d) for _, d in merged] == [2]


def test_it_changes_nothing_it_was_given_and_a_second_pass_changes_nothing():
    src = three()
    before = json.dumps(src)
    kept, _ = claimdedupe.dedupe(src)
    assert json.dumps(src) == before
    assert claimdedupe.dedupe(kept)[0] == kept


def test_distinct_claims_are_never_merged():
    growth = "Q3 sequential revenue growth fell from 147% to 45%, and revenue divided by compute expense fell from 2.08 to 1.7."
    rows = [claim(REPORT, 185),
            claim(growth, 190),  # a different fact 5 s later
            claim("Anthropic is said to have cut prices by about 50% in October.", 215),
            claim("Revenue growth was 45% last quarter.", 230),  # a different, shorter fact that happens to share a figure
            claim("Revenue growth was 147% the quarter before.", 240),  # conflicting figures
            claim(REPORT, 185, speaker="Other Person"),  # another speaker
            claim(REPORT, 400),  # the same point much later: said again, not restated
            claim(REPORT, None),  # no moment to compare
            claim(REPORT, 185, ep="rss:other")]  # another episode
    kept, merged = claimdedupe.dedupe(rows)
    assert kept == rows and merged == []


def test_a_role_or_unknown_speaker_matches_a_named_one_and_the_name_wins():
    kept, _ = claimdedupe.dedupe([claim(SHORT, 185, speaker="unknown"), claim(REPORT, 186, speaker=G)])
    assert [(c["text"], c["speaker"]) for c in kept] == [(REPORT, G)]
    kept, _ = claimdedupe.dedupe([claim(REPORT, 185, speaker="host"), claim(SHORT, 186, speaker="guest")])
    assert len(kept) == 1


def test_numbers_and_entities_are_read_the_way_a_person_would():
    assert claimdedupe.numbers(RANKED) == {"800", "900"}  # not the 1 of "S-1"
    assert claimdedupe.numbers("grew 1,200.0 or 2.08 in Q3") == {"1200", "2.08"}  # not the 3 of "Q3"
    assert {"commitment", "800"} <= claimdedupe.words(SHORT)


def test_ingest_lists_a_restated_point_once_with_the_ranking_readers_tag(tmp_path):
    from tests.test_library import make_run

    run = make_run(tmp_path, claim="Oracle capex doubles next year, driven by AI leases.")
    rep = json.loads((run / "report.json").read_text())
    ep = rep["episodes"][0]
    SPK = ep["signal"][0]["speaker"]  # whoever the shared fixture uses
    ep["signal"] = [{"text": "Oracle doubles capex next year on AI leases.", "speaker": SPK, "timestamp": 70}]
    ep["sections"][0]["claims"] = [{"text": "Oracle's capex doubles next year because of AI leases.", "speaker": SPK, "timestamp": 72}]
    (run / "report.json").write_text(json.dumps(rep))
    db = tmp_path / "lib.sqlite"
    library.ingest_run(run, db=db, transcripts=False)
    rows = [r for r in library.query_claims(db, limit=0) if r["episode_id"] == "ep1"]
    assert len(rows) == 1 and "NVDA" in rows[0]["tickers"]  # three wordings in, one claim out, with the ranking reader's tags


def test_published_claims_are_collapsed_in_place_and_only_that_file_changes(tmp_path):
    d = tmp_path / "2026-10-28"
    d.mkdir()
    (d / "episodes.json").write_text("[]")
    rows = three() + [claim("An unrelated point about hiring.", 900, title="T")]
    (d / "claims.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    res = published.dedupe_claims(tmp_path)
    assert res["2026-10-28"]["before"] == 4 and res["2026-10-28"]["after"] == 2
    assert res["2026-10-28"]["episodes"][EP]["removed"] == 2
    left = [json.loads(line) for line in (d / "claims.jsonl").read_text().splitlines()]
    assert [c["text"] for c in left] == [REPORT, "An unrelated point about hiring."] and left[0]["tickers"] == ["private:Anthropic"]
    assert (d / "episodes.json").read_text() == "[]"
    assert published.dedupe_claims(tmp_path)["2026-10-28"]["after"] == 2  # re-running changes nothing


def test_an_episode_page_lists_a_point_once_even_when_two_runs_worded_it_differently(tmp_path):
    root = tmp_path / "published"
    for name, text in (("2026-10-27", RANKED), ("2026-10-28", REPORT)):
        d = root / name
        d.mkdir(parents=True)
        (d / "episodes.json").write_text(json.dumps([{"episode_id": EP, "title": "A guest on the S-1", "source": "Show", "has_transcript": True}]))
        (d / "report.json").write_text(json.dumps({"date": name, "title": "t", "key_insights": ["x"], "episodes": [{"episode_id": EP, "headline": "h"}]}))
        row = claim(text, 185, title="A guest on the S-1", show="Show", published=name, run=name, url="https://example.com/e", link="https://example.com/e")
        (d / "claims.jsonl").write_text(json.dumps(row) + "\n")
    reg = site.build_episodes(site.load_runs(root))
    assert [c["text"] for c in reg[EP]["claims"]] == [REPORT]


def test_the_data_check_names_every_pair_that_restates_a_point_and_passes_clean_data(tmp_path):
    """Owner, 2026-10-28: this should have been caught by a test over the data. `restated_problems` compares all pairs."""
    problems = published.restated_problems(three(), "published/2026-10-28")
    assert len(problems) == 3 and all("published/2026-10-28" in m and "@3:05" in m for m in problems)  # every pair of the three
    assert published.restated_problems(claimdedupe.dedupe(three())[0], "x") == []
    assert published.restated_problems([claim(REPORT, 185), claim(REPORT, 400), claim(REPORT, None), claim(SHORT, 185, speaker="Other")], "x") == []
    d = tmp_path / "2026-10-28"
    d.mkdir()
    (d / "claims.jsonl").write_text("".join(json.dumps(r) + "\n" for r in three()))
    assert len(published.check_claims(tmp_path)) == 3
    published.dedupe_claims(tmp_path)
    assert published.check_claims(tmp_path) == []


def test_an_export_that_would_list_a_point_twice_is_refused_and_leaves_nothing_behind(tmp_path, monkeypatch):
    from tests.test_library import make_run

    run = make_run(tmp_path / "runs", claim="Oracle capex doubles next year, driven by AI leases.")
    rep = json.loads((run / "report.json").read_text())
    SPK = rep["episodes"][0]["signal"][0]["speaker"]
    rep["episodes"][0]["signal"] = [{"text": "Oracle doubles capex next year on AI leases.", "speaker": SPK, "timestamp": 70}]
    (run / "report.json").write_text(json.dumps(rep))
    root = tmp_path / "published"
    published.export(run, root=root, resolver=lambda *a, **k: {})  # merged at ingest: exports fine
    assert published.check_claims(root) == []
    monkeypatch.setattr(library, "_merge_restated", lambda claims: claims)  # a regression in the merge
    with pytest.raises(ValueError, match="listed twice"):
        published.export(run, root=root, name="again", resolver=lambda *a, **k: {})
    assert not (root / "again").exists()
    before = (root / run.name / "claims.jsonl").read_bytes()
    with pytest.raises(ValueError, match="listed twice"):  # a refusal for a name that exists keeps the old export too
        published.export(run, root=root, name=run.name, resolver=lambda *a, **k: {})
    assert (root / run.name / "claims.jsonl").read_bytes() == before


@pytest.mark.parametrize("a, b", [
    ("Acme will license the model to partners in 2027 at a 30% discount.", "Acme will not license the model to partners in 2027 at a 30% discount."),
    ("Revenue grew 45% year on year to $5 billion at Acme.", "Revenue grew 45 million year on year to $5 million at Acme."),
    ("Acme revenue grew 10 percent last quarter on cloud demand.", "Beta revenue grew 10 percent last quarter on cloud demand."),
    ("Acme raised its 2027 capex guidance to $50 billion after the quarter.", "Acme cut its 2027 capex guidance to $50 billion after the quarter."),
    ("Acme revenue grew 45% last quarter on strong cloud demand.", "Acme revenue fell 45% last quarter on strong cloud demand."),
    ("Acme reported $5B revenue and $2M profit last quarter on cloud demand.", "Acme reported $5M revenue and $2B profit last quarter on cloud demand."),
    ("Acme sold 10,000 GPUs to Beta Corp in the second quarter this year.", "Acme sold 10,000 GPUs to Gamma Corp in the second quarter this year."),
    ("Acme said it will not expand in Europe this year on weak demand.", "Acme said it will not cut Asia spending this year on weak demand."),
    ("Over 250 accounts spend more than $10 million a year at Acme.", "Over 250 accounts spend less than $10 million a year at Acme."),
    ("Acme bought the startup in the second quarter of this year for cash.", "Acme sold the startup in the second quarter of this year for cash."),
    ("Acme gained market share in cloud last quarter on lower prices.", "Acme lost market share in cloud last quarter on lower prices."),
    ("Acme is overvalued against its peers after the rally this year.", "Acme is undervalued against its peers after the rally this year."),
    ("Acme will spend $10 million per month on compute through 2027.", "Acme will spend $10 million per year on compute through 2027."),
    ("Margins reached 45 percent on cloud demand last quarter.", "Margins reached 45 on cloud demand last quarter."),
])
def test_claims_that_differ_in_polarity_scale_unit_or_subject_are_not_merged(a, b):
    assert not claimdedupe.same_point(claim(a, 100), claim(b, 100))
    assert len(claimdedupe.dedupe([claim(a, 100), claim(b, 100)])[0]) == 2


def test_a_shorter_claim_that_leaves_out_a_clause_is_still_the_same_point():
    long = "Acme lists commitments of $800 to $900 billion, shown as a footnote and not yet in the income statement."
    assert claimdedupe.same_point(claim(long, 100), claim("Commitments total roughly $800 to $900 billion at Acme.", 100))


def test_a_role_does_not_bridge_two_named_speakers():
    t = "Acme revenue grew 45% last quarter on strong cloud demand and new enterprise contracts."
    kept, _ = claimdedupe.dedupe([claim(t, 100, speaker="Ann Example"), claim(t + " ", 100, speaker="Host"), claim(t, 100, speaker="Bob Sample")])
    assert sorted(c["speaker"] for c in kept) == ["Ann Example", "Bob Sample"]


def test_non_numeric_timestamps_do_not_crash_the_check_or_the_dedupe():
    rows = [claim(REPORT, "3:05"), claim(REPORT, 185), claim(REPORT, None, title=None, episode_id=None)]
    assert len(claimdedupe.dedupe(rows)[0]) == 3
    assert published.restated_problems(rows, "x") == []


def test_tags_for_different_companies_keep_two_claims_apart():
    t = "The company expects capacity to double by the end of next year on strong demand."
    assert len(claimdedupe.dedupe([claim(t, 5, tickers=["NVDA"]), claim(t + " ", 5, tickers=["private:Acme"])])[0]) == 2
    assert len(claimdedupe.dedupe([claim(t, 5, tickers=["NVDA"]), claim(t + " ", 5, tickers=[])])[0]) == 1


def test_a_merged_claim_stays_a_ranked_claim_and_copies_share_nothing_with_the_input():
    src = three()
    kept, _ = claimdedupe.dedupe(src)
    assert kept[0]["source"] == "ranked"  # library.stored_scores reuses ranked claims
    one = [claim("A lone claim about nothing else.", 5, tickers=["X"])]
    out, _ = claimdedupe.dedupe(one)
    out[0]["tickers"].append("Y")
    assert one[0]["tickers"] == ["X"]


def test_the_verdict_does_not_depend_on_the_hash_seed():
    import subprocess
    import sys
    code = ("from wire import claimdedupe as c;"
            "a='Acme said it will not license the new model to partners in 2027 after talks.';"
            "b='Acme said it will not license the new model to partners in 2027 after long talks.';"
            "print(c.same_point({'timestamp':1,'text':a},{'timestamp':1,'text':b}))")
    seen = {subprocess.run([sys.executable, "-c", code], env={"PYTHONHASHSEED": str(n), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, capture_output=True, text=True).stdout
            for n in range(4)}
    assert seen == {"True\n"}


def test_dedupe_is_idempotent_when_tag_sets_overlap():
    """Three restatements tagged [A], [A, B], [B]: the first has no tag in common with the third, so a single pass can leave two;
    dedupe must reach a fixed point so the export gate never rejects its own output."""
    text = "Acme has $800 billion of commitments that are not in the income statement"
    claims = [claim(text, 100, tickers=["AAA"]), claim(text, 100, tickers=["AAA", "BBB"]), claim(text, 100, tickers=["BBB"])]
    once, _ = claimdedupe.dedupe(claims)
    twice, _ = claimdedupe.dedupe(once)
    assert len(once) == 1 and len(twice) == 1
    assert not claimdedupe.restated_pairs(once)
    assert sorted(once[0]["tickers"]) == ["AAA", "BBB"]


def test_opposite_verbs_keep_claims_apart_even_when_three_figures_are_shared():
    a = claim("Acme raised its 2027 revenue guidance from $10 billion to $20 billion", 100)
    b = claim("Acme cut its 2027 revenue guidance from $20 billion to $10 billion", 100)
    assert len(claimdedupe.dedupe([a, b])[0]) == 2
    assert claimdedupe.restated_pairs([a, b]) == []
