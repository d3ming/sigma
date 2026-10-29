"""The daily loop as an agent runs it (prompts/daily.md): today -> status -> check selected -> links -> report.

Every step goes through sigma.cli.main on a sandboxed repo root. Faked: the feed and iTunes finders, the transcript lookup,
the background transcribe process, YouTube captions and the web."""
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

from sigma import fetch as fetch_mod, people, report as report_mod, transcribe
from sigma import ingest
from sigma.ingest import Episode
from sigma.cli import main

from tests.helpers import STATUS_SHAPE, no_web, sandbox

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
RUN = "data/runs/" + YESTERDAY

JANE = [{"start": 0, "speaker": None, "text": "padding " * 750},
        {"start": 600, "speaker": None, "text": "our capex is 450 billion dollars next year and we keep building"},
        {"start": 1200, "speaker": None, "text": "gross margin is 38 percent now"},
        {"start": 1500, "speaker": None, "text": "the supply chain for advanced packaging will stay tight through the end of next year for everyone"}]
OMAR = [{"start": 0, "speaker": None, "text": "padding " * 750},
        {"start": 300, "speaker": None, "text": "we ran 420 clinical sites"},
        {"start": 600, "speaker": None, "text": "backlog stands at 880 units"},
        {"start": 900, "speaker": None, "text": "headcount grew to 640 people"}]
SHORT = [{"start": 0, "speaker": None, "text": "show notes " * 150}]  # 1,650 characters: a show description, not a transcript


OMAR_PAGE = "https://podcasts.apple.com/us/podcast/omar/id1?i=2&uo=4"


def episode(id, title, hours_old, source="widget", desc="", **kw):
    return Episode(id=id, source_id=source, source_name="Widget Show", tier=1, title=title, url=f"https://show.example/{id}",
                   published_at=datetime.now(timezone.utc) - timedelta(hours=hours_old), description=desc,
                   audio_url=f"https://cdn.example/{id}.mp3", **kw)


@pytest.fixture
def day(tmp_path, monkeypatch):
    """`sigma today --run-name <yesterday>` has run. The feed has Jane (also found by the people search), Omar, a
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


def test_report_checks_numbers_against_captions(day, capsys, monkeypatch):
    """check report --captions: one line per wrong number, naming each place that disagrees; a whole video offset is named once."""
    root = day
    words = [(w, 0) for w in "a billion and a half one and a half million two billion and a half".split()]
    spoken = report_mod.spoken_numbers(words)
    assert spoken == [(0, "1.5"), (0, "1.5"), (0, "2.5")]
    for phrase in ("a billion and a half million", "two billion and a half million"):
        assert report_mod.spoken_numbers([(w, 0) for w in phrase.split()]) == []
    near = {"episode_id": "synthetic", "signal": [{"text": "Raised 1.5 billion", "timestamp": 120}], "sections": []}
    assert report_mod._number_warnings(near, spoken[:1]) == []
    wrong = {"episode_id": "synthetic", "signal": [{"text": "Raised 1.6 billion", "timestamp": 120}], "sections": []}
    distant = {"episode_id": "synthetic", "signal": [{"text": "Raised 1.5 billion", "timestamp": 121}], "sections": []}
    assert len(report_mod._number_warnings(wrong, spoken[:1])) == 1
    assert len(report_mod._number_warnings(distant, spoken[:1])) == 1
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    path = write(root, "report.json", report_json())
    captions = {"abcdefghijk": [(540, "our capex is 450 billion dollars"), (1140, "gross margin is 38 percent")],  # a minute early
                "ddddddddddd": [(0, "we ran 420 clinical sites"), (300, "backlog stands at 880 units"), (600, "headcount grew to 640 people")]}
    monkeypatch.setattr(transcribe, "from_youtube", lambda vid: [{"start": t, "speaker": None, "text": x} for t, x in captions[vid]])
    main(["links", str(root / RUN)])
    capsys.readouterr()
    with pytest.raises(SystemExit):
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
        with pytest.raises(SystemExit):
            main(["check", "report", path, "--captions"])
        skipped = [l for l in capsys.readouterr().out.splitlines() if "skipped" in l]
        assert len(skipped) == 2 and {"rss:jane", "rss:omar"} == {w for l in skipped for w in ("rss:jane", "rss:omar") if w in l}


def test_status_follows_a_stuck_transcribe(day, monkeypatch):
    """The agent must restart a transcribe that died, wait for one that is alive, and never start a second."""
    root, run = day, day / RUN
    monkeypatch.setattr(fetch_mod, "whisper_python", lambda: "/Users/me/My Venv/bin/python")  # a path with a space must be quoted
    m = manifest(root)
    m["episodes"][0].update(has_transcript=False)  # one episode still needs whisper
    (run / "manifest.json").write_text(json.dumps(m))
    (run / "transcribe.queued").write_text("999999999")  # the queued process died before starting
    d = status(root)
    assert d["stage"] == "transcribe" and d["next"]["type"] == "command" and d["next"]["command"].startswith("nohup '/Users/me/My Venv/bin/python' -m sigma.cli transcribe ")
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
    assert d["exists"] is False and d["stage"] == "fetch" and d["next"]["command"] == "sigma daily --hours 48 --run-name nothing-yet"
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
    """AGENTS.md: manifest.json is written only through sigma.manifest.update, because transcribe runs for hours while
    other commands edit the same file. Hold the lock and every writer must wait, then still land its edit."""
    root, run = day, day / RUN
    main(["check", "selected", write(root, "selected.json", selected(good_picks()))])
    commands = {"mark": (["mark", "select", "start", "--run", str(run)], lambda m: m["timing"]["select"]["start"]),
                "links": (["links", str(run)], lambda m: m["episodes"][0]["youtube_url"]),
                }
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


def test_doctor_exits_nonzero_only_when_a_check_fails(monkeypatch):
    """prompts/daily.md: `sigma doctor` names what is missing and exits 1; a warning alone is not a failure."""
    from sigma import doctor

    monkeypatch.setattr(doctor, "CHECKS", [("a", lambda: ("ok", "fine")), ("b", lambda: ("warn", "meh"))])
    main(["doctor"])
    monkeypatch.setattr(doctor, "CHECKS", [("a", lambda: ("ok", "fine")), ("c", lambda: (_ for _ in ()).throw(RuntimeError("boom")))])
    with pytest.raises(SystemExit) as e:
        main(["doctor"])
    assert e.value.code == 1


def test_doctor_warns_until_the_pre_push_hook_is_set_up(monkeypatch, tmp_path):
    """AGENTS.md (run scripts/setup.sh once per clone): `sigma doctor` is where an agent on a fresh clone finds out it has not."""
    import subprocess

    from sigma import doctor

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    assert doctor.check_hooks()[0] == "warn"
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=tmp_path, check=True)
    assert doctor.check_hooks()[0] == "ok"


def test_doctor_checks_the_configured_data_root(monkeypatch, tmp_path):
    from sigma import doctor

    monkeypatch.setenv("SIGMA_DATA_ROOT", str(tmp_path / "private-data"))
    assert doctor.check_data_dir()[0] == "ok"
    assert (tmp_path / "private-data").is_dir()
