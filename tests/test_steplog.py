import json
import sys
from datetime import datetime, timezone

from wire import steplog
from wire.cli import main


def _lines(p):
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_run_times_a_command_and_passes_its_exit_code_on(tmp_path):
    log = tmp_path / "steps.jsonl"
    assert steplog.run_step(log, "ok", [sys.executable, "-c", "pass"]) == 0
    assert steplog.run_step(log, "bad", [sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert steplog.run_step(log, "missing", ["/no/such/binary"]) == 127
    ok, bad, missing = _lines(log)
    assert ok["step"] == "ok" and ok["exit"] == 0 and ok["seconds"] >= 0 and ok["start"] <= ok["end"]
    assert bad["exit"] == 3 and missing["exit"] == 127


def test_marks_pair_into_steps_and_an_unfinished_one_stays_open(tmp_path):
    log = tmp_path / "steps.jsonl"
    for r in [{"step": "scan", "event": "start", "at": "2026-10-29T15:14:00+00:00"},
              {"step": "scan", "event": "end", "at": "2026-10-29T15:29:00+00:00"},
              {"step": "review", "event": "start", "at": "2026-10-29T15:40:00+00:00"}]:
        steplog.append(log, r)
    log.write_text(log.read_text() + "not json\n")
    steps = steplog.load(log)
    assert [(s["step"], s["seconds"]) for s in steps] == [("scan", 900), ("review", None)]
    assert "never ended" in steps[1]["note"]


def test_table_shows_lateness_the_gap_no_step_claims_and_the_slowest_step(tmp_path):
    log = tmp_path / "steps.jsonl"
    steplog.append(log, {"step": "run-start", "event": "begin", "at": "2026-10-29T15:14:06+00:00",
                         "scheduled": "2026-10-29T15:00:00+00:00", "late_seconds": 846})
    steplog.append(log, {"step": "scan", "start": "2026-10-29T15:14:10+00:00", "end": "2026-10-29T15:29:10+00:00", "seconds": 900, "exit": 0})
    steplog.append(log, {"step": "tests", "start": "2026-10-29T15:40:10+00:00", "end": "2026-10-29T15:42:10+00:00", "seconds": 120, "exit": 1})
    out = steplog.table(steplog.load(log))
    assert "14m06s late" in out
    assert "(gap)" in out and "10m59s" not in out and "11m00s" in out  # 15:29:10 to 15:40:10
    assert "slowest: scan (15m00s)" in out
    assert "exit 1" in out


def test_begin_records_how_late_the_run_started(tmp_path):
    log = tmp_path / "steps.jsonl"
    r = steplog.begin(log, "08:00")
    due = datetime.fromisoformat(r["scheduled"])
    assert due.astimezone(steplog.PT).strftime("%H:%M") == "08:00"
    assert r["late_seconds"] == round((datetime.fromisoformat(r["at"]) - due).total_seconds())


def test_the_cli_writes_and_prints_the_table(tmp_path, capsys):
    log = str(tmp_path / "s.jsonl")
    main(["step", "--log", log, "mark", "build", "start"])
    main(["step", "--log", log, "mark", "build", "end"])
    try:
        main(["step", "--log", log, "run", "tests", "--", sys.executable, "-c", "raise SystemExit(2)"])
    except SystemExit as e:
        assert e.code == 2
    capsys.readouterr()
    main(["step", "--log", log, "table"])
    out = capsys.readouterr().out
    assert "build" in out and "tests" in out and "exit 2" in out
