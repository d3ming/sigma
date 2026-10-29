"""The daily loop as an agent runs it (prompts/daily.md): today -> status -> check selected -> links -> report -> tmtb-import.

Every step goes through wire.cli.main on a sandboxed repo root. Faked: the feed and iTunes finders, the transcript lookup,
the background transcribe process, YouTube captions and the web."""
import copy
import fcntl
import io
import json
import os
import threading
import time
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from wire import fetch as fetch_mod, people, transcribe
from wire import ingest, library, published
from wire.ingest import Episode
from wire.cli import main

from tests.helpers import STATUS_SHAPE, no_web, sandbox, spoken

EMAIL = Path(__file__).parent / "fixtures" / "reference_email.txt"
TWO_LINE_EMAIL = Path(__file__).parent / "fixtures" / "tmtb-2026-10-22.txt"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
RUN = "runs/" + YESTERDAY

# What the two full transcripts say, by second (one segment a minute; each ends at 29:00).
JANE = spoken({600: "our capex is 450 billion dollars next year and we keep building",
               1200: "gross margin is 38 percent now",
               1500: "the supply chain for advanced packaging will stay tight through the end of next year for everyone"})
OMAR = spoken({300: "we ran 420 clinical sites", 600: "backlog stands at 880 units", 900: "headcount grew to 640 people"})
SHORT = [{"start": 0, "speaker": None, "text": "show notes " * 150}]  # 1,650 characters: a show description, not a transcript


OMAR_PAGE = "https://podcasts.apple.com/us/podcast/omar/id1?i=2&uo=4"


def episode(id, title, hours_old, source="widget", desc="", **kw):
    return Episode(id=id, source_id=source, source_name="Widget Show", tier=1, title=title, url=f"https://show.example/{id}",
                   published_at=datetime.now(timezone.utc) - timedelta(hours=hours_old), description=desc,
                   audio_url=f"https://cdn.example/{id}.mp3", **kw)


@pytest.fixture
def day(tmp_path, monkeypatch):
    """`wire today --run-name <yesterday>` has run. The feed has Jane (also found by the people search), Omar, a
    description-only episode, a three-day-old one and a replay."""
    root = sandbox(tmp_path, monkeypatch)
    jane = episode("rss:jane", "Jane Placeholder on robots", 3, source="person:Jane Placeholder", youtube_id="abcdefghijk")
    feeds = {"widget": [episode("rss:jane2", "Jane Placeholder on robots", 3),
                        episode("rss:omar", "Omar Example on rates", 5),
                        episode("rss:pat", "Pat Roe on chips", 6)],
             "gadget": [episode("rss:old", "Three days ago", 72),
                        episode("rss:replay", "Replay: classic", 7),
                        episode("rss:aired", "Friar on AI", 8, desc="This episode originally aired in May.")]}
    feeds["widget"][1].url = OMAR_PAGE
    monkeypatch.setattr(ingest, "find", lambda src, now, days: (feeds[src.id], "rss"))
    monkeypatch.setitem(people.FINDERS, "itunes", lambda p, now, days: [jane])
    transcripts = {"rss:jane": JANE, "rss:omar": OMAR, "rss:pat": SHORT}
    monkeypatch.setattr(fetch_mod, "get_transcript", lambda ep, budget: (transcripts[ep.id], "podcast:transcript"))
    monkeypatch.setattr(fetch_mod, "whisper_python", lambda: "py")
    queued = {}
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: queued.setdefault("p", type("P", (), {"pid": os.getpid()})()))
    no_web(monkeypatch)
    monkeypatch.setattr(requests, "get", lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"results": []}})())  # iTunes finds nothing
    main(["today", "--run-name", YESTERDAY])
    return root


def status(root, *extra):
    out = io.StringIO()
    with redirect_stdout(out):
        main(["status", str(root / RUN), "--json", *extra])
    STATUS_SHAPE.validate(d := json.loads(out.getvalue()))  # schema/status.schema.json is what the agent reads
    return d


def transcribe_finished(root):
    """The queued transcribe ran out of budget before the description-only episode: it ended with one still untranscribed."""
    (root / RUN / "transcribe.queued").write_text("999999999")
    main(["mark", "transcribe", "end", "--run", str(root / RUN)])


def scored(root):
    """The scoring stages after rank-prep: a reader per batch (Jane 8, Omar 6), then rank-merge into scores.json."""
    run = root / RUN
    for f in sorted((run / "rank").glob("batch-*-in.json")):
        rows = [{**{k: it[k] for k in ("episode_id", "title", "url", "source", "tier", "published")},
                 "score": {"rss:jane": 8, "rss:omar": 6}[it["episode_id"]], "reason": "why", "claims": []}
                for it in json.loads(f.read_text())]
        f.with_name(f.name.replace("-in", "-out")).write_text(json.dumps(rows))
    main(["rank-merge", str(run)])


def write(root, name, data):
    (root / RUN / name).write_text(json.dumps(data))
    return str(root / RUN / name)


def manifest(root):
    return json.loads((root / RUN / "manifest.json").read_text())


def pick(id, guest, why="new capex numbers", url=None, **kw):
    return {"episode_id": id, "title": "T", "show": "Widget Show", "url": url or f"https://show.example/{id}", "guests": [{"name": guest, "role": "CEO"}],
            "kind": "exec", "why": why, **kw}


def cite(text, ts):
    return {"text": text, "speaker": "Jane Placeholder", "timestamp": ts}


def report_json(**override):
    filler = [cite("Plans another site", 60), cite("Hiring for the new line", 120)]
    jane = {"episode_id": "rss:jane", "headline": "Jane on robots", "url": "https://traffic.megaphone.fm/jane.mp3",
            "signal": [{**cite("Capex hits 450 billion", 600), "our_read": "Demand is real."}, *filler],
            "interests": "Early investor in Acme.",
            "sections": [{"title": "Margins", "body": "Margin is rising.",
                          "claims": [cite("Margin of 38 percent", 900), cite("Opens 777 sites", 1000)]}]}
    omar = {"episode_id": "rss:omar", "headline": "Omar on rates", "url": OMAR_PAGE,
            "youtube_url": "https://www.youtube.com/watch?v=ddddddddddd",
            "signal": [cite("Runs 420 sites", 300), cite("Backlog of 880 units", 600), cite("Headcount of 640", 900)],
            "sections": [{"title": "Rates", "body": "Rates matter.", "claims": []}]}
    nadia = {"episode_id": "rss:pat", "headline": "Pat on chips", "url": "https://show.example/rss:pat",
             "signal": [{**cite("Chips are tight", None), "speaker": "unknown"}] * 3,
             "sections": [{"title": "Chips", "body": "Chips are tight.", "claims": []}]}
    eps = [jane, omar, nadia]
    return {"date": YESTERDAY, "title": "Podcast Intel: test", "run_dir": RUN, "key_insights": ["k1", "k2", "k3"],
            "essential": [{"episode_id": e["episode_id"], "headline": e["headline"], "show": "Widget Show", "guests": "Host and guest"}
                          for e in eps], "episodes": eps, **override}


def good_picks():
    return [pick("rss:jane", "Jane Placeholder"), pick("rss:omar", "Omar Example", url=OMAR_PAGE),
            pick("rss:pat", "Pat Roe", "Strong exec pick; fallback text only, whisper pending.", fallback_text=True)]


def selected(picks):
    return {"date": YESTERDAY, "run_dir": RUN, "selected_by": "t", "episodes": picks}


def test_today_through_report(day, capsys, monkeypatch):
    """prompts/daily.md: status names one next action at every step, and each file the agent writes is checked before it counts."""
    root = day
    # today: Jane is found once (feed copy dropped for the people-search copy, listed first); out-of-window and replays are
    # excluded with a reason; a show-description-sized text is flagged as fallback, not a transcript.
    m = manifest(root)
    assert [e["episode_id"] for e in m["episodes"]] == ["rss:jane", "rss:omar", "rss:pat"]
    assert {x["episode_id"]: x["why"] for x in m["excluded"]} == {"rss:old": "outside window", "rss:replay": "rerun", "rss:aired": "rerun"}
    rows = {e["episode_id"]: e for e in m["episodes"]}
    assert rows["rss:jane"]["has_transcript"] and rows["rss:pat"]["fallback_text"] and not rows["rss:pat"]["has_transcript"]
    assert (root / RUN / "transcribe.queued").read_text() == str(os.getpid())  # the pid of the process daily started

    d = status(root)
    assert (d["stage"], d["next"]["type"]) == ("transcribe", "wait")  # a transcribe was just queued: do not start another
    transcribe_finished(root)
    d = status(root)
    assert (d["stage"], d["next"]["command"]) == ("rank_prep", f"wire rank-prep {root / RUN}")  # every transcript is scored once, before select
    main(["rank-prep", str(root / RUN)])
    assert status(root)["stage"] == "readers"
    scored(root)
    d = status(root)
    assert (d["stage"], d["next"]["prompt"]) == ("select", "prompts/select.md")
    assert sorted(e["episode_id"] for e in json.loads((root / RUN / "scores.json").read_text())["episodes"]) == ["rss:jane", "rss:omar"]  # the fallback-text episode is not read

    # selected.json: every bad pick list is refused, and status shows the same blockers
    refused = {
        "no picks": selected([]),
        "a fallback episode not flagged": selected([pick("rss:pat", "Pat Roe")]),
        "flagged but not said in why": selected([pick("rss:pat", "Pat Roe", "Great pick", fallback_text=True)]),
        "one person twice": selected([pick("rss:jane", "Jane Placeholder"), pick("rss:omar", "jane  PLACEHOLDER")]),
        "a replay": selected([pick("rss:replay", "Pat Example")]),
    }
    for why, data in refused.items():
        with pytest.raises(SystemExit):
            main(["check", "selected", write(root, "selected.json", data)])
        assert status(root)["blockers"], why
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    d = status(root)
    assert d["stage"] == "links" and d["next"]["command"].startswith("wire links")

    # links: offline, so Jane's known YouTube id and Omar's Apple page (tracking suffix cut) are what is found
    capsys.readouterr()
    main(["links", str(root / RUN)])
    sel = {e["episode_id"]: e for e in json.loads((root / RUN / "selected.json").read_text())["episodes"]}
    assert sel["rss:jane"]["youtube_url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert sel["rss:omar"]["listen_url"] == "https://podcasts.apple.com/us/podcast/omar/id1?i=2" and "youtube_url" not in sel["rss:omar"]
    assert sel["rss:pat"]["listen_url"] == "https://show.example/rss:pat"
    assert (d := status(root))["stage"] == "report" and d["next"]["prompt"] == "prompts/report.md"

    # report.json: nothing that breaks the grounding rules reaches report.md
    def broken(edit):
        r = copy.deepcopy(report_json())
        edit(r)
        return r

    jane = lambda r: r["episodes"][0]
    refused = {
        "a cite with no speaker": broken(lambda r: jane(r)["signal"][0].pop("speaker")),
        "episodes not matching essential": broken(lambda r: jane(r).update(episode_id="rss:other")),
        "holdings-like text": broken(lambda r: r["essential"][0].update(guests="holding 5%")),
        "a listen_url that is a tracking redirect": broken(lambda r: r["essential"][0].update(listen_url="https://chrt.fm/track/x")),
        "a timestamp past the end of the transcript": broken(lambda r: jane(r)["signal"][0].update(timestamp=4000)),
        "no timestamp on a real transcript": broken(lambda r: jane(r)["signal"][0].update(timestamp=None)),
        "a timestamp on a description-only episode": broken(lambda r: r["episodes"][2]["signal"][0].update(timestamp=5)),
        "12 words copied from the transcript": broken(lambda r: jane(r)["sections"][0].update(
            body="Management said the supply chain for advanced packaging will stay tight through the end soon")),
        "a pick missing from the report": broken(lambda r: [r["essential"].pop(), r["episodes"].pop()]),
    }
    for why, data in refused.items():
        with pytest.raises(SystemExit):
            main(["report", write(root, "report.json", data)])
        assert not (root / RUN / "report.md").exists(), why
        assert status(root)["stage"] == "report" and status(root)["blockers"], why
    # 11 copied words are a paraphrase; the one number spoken 300 s after its timestamp is a warning, not a refusal
    eleven = broken(lambda r: jane(r)["sections"][0].update(body="Management said the supply chain for advanced packaging will stay tight through the"))
    path = write(root, "report.json", eleven)
    monkeypatch.setattr(published, "ROOT", root / "published")
    monkeypatch.delenv("PA_NO_PUBLISHED")
    monkeypatch.delenv("PA_NO_LIBRARY")
    monkeypatch.setattr(library, "DEFAULT_DB", root / "lib.sqlite")
    main(["tmtb-import", str(EMAIL)])  # writes missed.md and seeds.json beside the report: they quote the reference newsletter
    capsys.readouterr()
    main(["report", path])
    out = capsys.readouterr().out
    warnings = [l for l in out.splitlines() if "warning:" in l]
    assert len(warnings) == 2 and "number 38 not spoken within 120s of 0:15:00 (ts 900s)" in warnings[0] and "nearest mention 0:20:00 (300s later)" in warnings[0]
    assert "sections[0].claims[1]: number 777" in warnings[1] and "not spoken anywhere in the transcript" in warnings[1]
    md = (root / RUN / "report.md").read_text()
    assert "1. **[Jane on robots](https://www.youtube.com/watch?v=abcdefghijk)**" in md  # YouTube first
    assert "2. **[Omar on rates](https://www.youtube.com/watch?v=ddddddddddd)**" in md
    assert "3. **[Pat on chips](https://show.example/rss:pat)**" in md and ".mp3" not in md  # never the audio file
    assert "[Jane Placeholder, [0:10:00](https://www.youtube.com/watch?v=abcdefghijk&t=600s)]" in md
    assert "- Chips are tight [unknown]" in md  # no transcript, no timestamp
    assert "(our read: Demand is real.)" in md and "**Interests to note:** Early investor in Acme." in md

    # published/<run>: our own writing and slim metadata only
    pub = root / "published" / YESTERDAY
    assert sorted(p.name for p in pub.iterdir()) == ["claims.jsonl", "episodes.json", "report.json", "report.md", "scores.json", "selected.json"]
    ep_rows = json.loads((pub / "episodes.json").read_text())
    assert [e["episode_id"] for e in ep_rows] == ["rss:jane", "rss:omar", "rss:pat"]
    assert not any(k in e for e in ep_rows for k in ("description", "audio_url", "file", "fallback_text"))

    os.utime(root / RUN / "report.md", (os.path.getmtime(root / RUN / "report.json") - 60,) * 2)  # report.json edited after rendering
    d = status(root)
    assert d["stage"] == "render" and d["next"]["command"] == f"wire report {root / RUN}/report.json"
    main(["report", path])

    # the report is in the library the moment it renders
    capsys.readouterr()
    main(["library", "query", "--text", "Capex", "--db", str(root / "lib.sqlite"), "--json"])
    claim, = json.loads(capsys.readouterr().out)
    assert claim["link"] == "https://www.youtube.com/watch?v=abcdefghijk&t=600s" and claim["speaker"] == "Jane Placeholder"

    # done: the agent commits published/ and records it
    d = status(root)
    assert d["stage"] == "publish" and d["next"]["command"] == f"wire mark publish end --run {root / RUN}"
    main(["mark", "publish", "end", "--run", str(root / RUN)])
    assert status(root)["stage"] == "done"
    t = manifest(root)["timing"]
    assert t["select"]["end"] and t["report"]["start"] and t["report"]["end"] and t["publish"]["end"]  # stamped by status --record / report
    capsys.readouterr()
    main(["stats", "--runs", str(root / "runs")])
    assert YESTERDAY in capsys.readouterr().out


def test_report_checks_numbers_against_captions(day, capsys, monkeypatch):
    """check report --captions: one line per wrong number, naming each place that disagrees; a whole video offset is named once."""
    root = day
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    path = write(root, "report.json", report_json())
    captions = {"abcdefghijk": [(540, "our capex is 450 billion dollars"), (1140, "gross margin is 38 percent")],  # a minute early
                "ddddddddddd": [(0, "we ran 420 clinical sites"), (300, "backlog stands at 880 units"), (600, "headcount grew to 640 people")]}
    monkeypatch.setattr(transcribe, "from_youtube", lambda vid: [{"start": t, "speaker": None, "text": x} for t, x in captions[vid]])
    main(["links", str(root / RUN)])
    capsys.readouterr()
    main(["check", "report", path, "--captions"])
    lines = [l for l in capsys.readouterr().out.splitlines() if "warning:" in l]
    jane = [l for l in lines if "rss:jane" in l]
    assert len(jane) == 2 and all("[transcript, captions]" in l for l in jane)  # each wrong cite is reported once, naming both sources
    assert "transcript: nearest mention 0:20:00 (300s later)" in jane[0] and "captions: nearest mention 0:19:00 (240s later)" in jane[0]
    assert "number 777" in jane[1]
    omar = [l for l in lines if "rss:omar" in l]
    assert sum("not spoken within 120s" in l for l in omar) == 3 and sum("cite timestamps run 300s later" in l for l in omar) == 1
    # a video whose captions cannot be had is one "skipped" line, never a crash or a pass
    for fetch in (lambda vid: (_ for _ in ()).throw(OSError("network down")), lambda vid: [], lambda vid: [{"nope": 1}]):
        monkeypatch.setattr(transcribe, "from_youtube", fetch)
        main(["check", "report", path, "--captions"])
        skipped = [l for l in capsys.readouterr().out.splitlines() if "skipped" in l]
        assert len(skipped) == 2 and {"rss:jane", "rss:omar"} == {w for l in skipped for w in ("rss:jane", "rss:omar") if w in l}


def test_tmtb_import_measures_recall_on_yesterdays_run(day, capsys, monkeypatch):
    """AGENTS.md: the reference newsletter arrives after the report, so tmtb-import checks yesterday's run by default."""
    root = day
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    capsys.readouterr()
    main(["tmtb-import", str(EMAIL)])
    # Jane and Omar are in the run and picked; the third episode (Pat Roe and Leo Test) has no match anywhere
    rec = manifest(root)["recall"]
    assert (rec["tmtb"], rec["hits"], rec["found_in_run"], rec["picks"]) == (3, 2, 2, 3) and rec["recall"] == 0.667
    assert (root / RUN / "missed.md").read_text().startswith("# Missed vs reference: 1 of 3")
    assert "recall: our picks hit 2/3 (67%)" in capsys.readouterr().out
    transcribe_finished(root)
    assert "missed.md exists" in " ".join(status(root)["notes"])  # the agent is told to read it before selecting
    # the unnumbered two-line email format: six episodes, and only the one whose guest is in the run counts as found
    other = root / "runs" / "other"
    other.mkdir()
    (other / "manifest.json").write_text(json.dumps({"episodes": [
        {"episode_id": "rss:o", "title": "Orrin Vance: Factory Financing and the Substrate Bottleneck", "source": "Morning Desk"}]}))
    main(["tmtb-import", str(TWO_LINE_EMAIL), "--run", str(other)])
    assert (other / "missed.md").read_text().startswith("# Missed vs reference: 5 of 6")
    with pytest.raises(SystemExit):  # an email in an unknown format must not overwrite missed.md with an empty list
        main(["tmtb-import", str(root / "people.yaml"), "--run", str(other)])
    assert (other / "missed.md").read_text().startswith("# Missed vs reference: 5 of 6")


def test_status_follows_a_stuck_transcribe(day, monkeypatch):
    """The agent must restart a transcribe that died, wait for one that is alive, and never start a second."""
    root, run = day, day / RUN
    monkeypatch.setattr(fetch_mod, "whisper_python", lambda: "/Users/me/My Venv/bin/python")  # a path with a space must be quoted
    m = manifest(root)
    m["episodes"][0].update(has_transcript=False)  # one episode still needs whisper
    (run / "manifest.json").write_text(json.dumps(m))
    (run / "transcribe.queued").write_text("999999999")  # the queued process died before starting
    d = status(root)
    assert d["stage"] == "transcribe" and d["next"]["type"] == "command" and d["next"]["command"].startswith("nohup '/Users/me/My Venv/bin/python' -m wire.cli transcribe ")
    assert " >> " in d["next"]["command"]  # appends: the first attempt's log survives
    (run / "transcribe.lock").write_text(str(os.getpid()))
    assert status(root)["next"]["type"] == "wait" and status(root)["stages"]["transcribe"] == "running"
    (run / "transcribe.lock").write_text("999999999")
    m["timing"] = {"transcribe": {"start": "2026-10-23T10:00:00+00:00"}}
    (run / "manifest.json").write_text(json.dumps(m))
    assert status(root)["stages"]["transcribe"] == "failed"  # started, no end, nobody running
    # a log written seconds ago with no lock yet is a transcribe still starting; an hour-old one is a dead run
    (run / "transcribe.lock").unlink()
    (run / "transcribe.queued").unlink()
    m["timing"] = {}
    (run / "manifest.json").write_text(json.dumps(m))
    (run / "transcribe.log").write_text("x")
    assert status(root)["next"]["type"] == "wait"
    os.utime(run / "transcribe.log", (time.time() - 3600,) * 2)
    assert status(root)["next"]["type"] == "command"
    # a run that does not exist: status says how to start it and creates nothing
    d = json.loads(subprocess_free_status(root / "runs" / "nothing-yet"))
    assert d["exists"] is False and d["stage"] == "fetch" and d["next"]["command"] == "wire daily --hours 48 --run-name nothing-yet"
    assert not (root / "runs" / "nothing-yet").exists()
    # today on a run that exists shows its status and does not fetch again
    before = (run / "manifest.json").read_text()
    out = io.StringIO()
    with redirect_stdout(out):
        main(["today", "--run-name", YESTERDAY])
    assert "stage: transcribe" in out.getvalue() and (run / "manifest.json").read_text() == before


def subprocess_free_status(run):
    out = io.StringIO()
    with redirect_stdout(out):
        main(["status", str(run), "--json"])
    return out.getvalue()


def test_status_stamps_stage_times_once(day):
    """`status --record` is how select and report durations get into the stats table: each is stamped once, never negative."""
    root, run = day, day / RUN
    transcribe_finished(root)
    main(["rank-prep", str(run)])
    scored(root)
    write(root, "selected.json", selected(good_picks()))
    os.utime(run / "selected.json", (time.time() - 3600,) * 2)  # the picks were written before anyone looked at the run
    assert status(root, "--record")["recorded"] == ["select start", "select end", "report start"]
    assert status(root, "--record")["recorded"] == []
    t = manifest(root)["timing"]["select"]
    assert t["seconds"] >= 0 and t["start"] <= t["end"]


def test_commands_that_edit_the_manifest_wait_for_the_lock(day):
    """AGENTS.md: manifest.json is written only through wire.manifest.update, because transcribe runs for hours while
    other commands edit the same file. Hold the lock and every writer must wait, then still land its edit."""
    root, run = day, day / RUN
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    commands = {"mark": (["mark", "select", "start", "--run", str(run)], lambda m: m["timing"]["select"]["start"]),
                "links": (["links", str(run)], lambda m: m["episodes"][0]["youtube_url"]),
                "tmtb-import": (["tmtb-import", str(EMAIL), "--run", str(run)], lambda m: m["recall"])}
    for name, (argv, landed) in commands.items():
        before = json.dumps(manifest(root))
        with open(run / "manifest.json.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            t = threading.Thread(target=main, args=(argv,))
            t.start()
            t.join(0.05)
            assert t.is_alive() and json.dumps(manifest(root)) == before, name
            fcntl.flock(lock, fcntl.LOCK_UN)
        t.join(5)
        assert not t.is_alive() and landed(manifest(root)), name


@pytest.mark.parametrize("n", [1, 7])
def test_any_number_of_picks_is_valid(tmp_path, n):
    """prompts/select.md: there is no fixed count; pick every episode that clears the bar, at least one."""
    (tmp_path / "selected.json").write_text(json.dumps(selected([pick(f"rss:{i}", f"Guest {i}") for i in range(n)])))
    main(["check", "selected", str(tmp_path / "selected.json")])


def test_doctor_exits_nonzero_only_when_a_check_fails(monkeypatch):
    """prompts/daily.md: `wire doctor` names what is missing and exits 1; a warning alone is not a failure."""
    from wire import doctor

    monkeypatch.setattr(doctor, "CHECKS", [("a", lambda: ("ok", "fine")), ("b", lambda: ("warn", "meh"))])
    main(["doctor"])
    monkeypatch.setattr(doctor, "CHECKS", [("a", lambda: ("ok", "fine")), ("c", lambda: (_ for _ in ()).throw(RuntimeError("boom")))])
    with pytest.raises(SystemExit) as e:
        main(["doctor"])
    assert e.value.code == 1


def test_doctor_warns_until_the_pre_push_hook_is_set_up(monkeypatch, tmp_path):
    """AGENTS.md (run scripts/setup.sh once per clone): `wire doctor` is where an agent on a fresh clone finds out it has not."""
    import subprocess

    from wire import doctor

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    assert doctor.check_hooks()[0] == "warn"
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=tmp_path, check=True)
    assert doctor.check_hooks()[0] == "ok"


def test_doctor_checks_that_data_links_to_darkroom(monkeypatch, tmp_path):
    """scripts/setup.sh links data/ to darkroom/wire; a real folder or a dead link is something `wire doctor` names."""
    from wire import doctor

    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    assert doctor.check_data_link()[0] == "warn"
    (tmp_path / "data").rmdir()
    (tmp_path / "data").symlink_to(tmp_path / "darkroom-wire")
    assert doctor.check_data_link()[0] == "fail"
    (tmp_path / "darkroom-wire").mkdir()
    assert doctor.check_data_link()[0] == "ok"
