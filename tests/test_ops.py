import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from wire import timing
from wire.cli import main


def test_stage_times_split_idle_from_active_and_stats_prints_the_trend(tmp_path, capsys):
    m = {"episodes": []}
    for st, a, b in [("fetch", "04:00", "04:05"), ("transcribe", "04:05", "04:15"), ("select", "09:00", "09:03"),
                     ("report", "09:03", "09:05")]:
        timing.apply(m, st, "start", f"2026-10-23T{a}:00+00:00")
        timing.apply(m, st, "end", f"2026-10-23T{b}:00+00:00")
    e2e = m["timing"]["e2e"]
    assert m["timing"]["fetch"]["seconds"] == 300
    assert e2e["active_seconds"] == 20 * 60 and e2e["idle_seconds"] == 4 * 3600 + 45 * 60  # 04:15 to 09:00 is waiting, not work
    assert e2e["seconds"] == 5 * 3600 + 5 * 60
    run = tmp_path / "2026-10-22"
    run.mkdir()
    ep = {"title": "x", "source": "Show", "source_tag": "", "tier": 2, "audio_url": None, "published": "2026-10-22"}
    (run / "manifest.json").write_text(json.dumps({"episodes": [{**ep, "episode_id": "a", "has_transcript": True},
                                                                {**ep, "episode_id": "b", "has_transcript": False}],
                                                   "recall": {"tmtb": 3, "hits": 2, "recall": 0.667}}))
    main(["mark", "select", "start", "--run", str(run)])
    main(["mark", "select", "end", "--run", str(run)])
    main(["stats", "--runs", str(tmp_path)])
    out = capsys.readouterr().out
    assert "2026-10-22" in out and "1/2" in out and "2/3 (67%)" in out  # one of two transcribed; two of TMTB's three found


def test_event_log_leaves_a_failing_command_unchanged_and_two_writers_never_interleave(tmp_path, monkeypatch):
    """Stated rules: logging never changes a command's result; concurrent appends leave whole lines only."""
    argv = ["check", "no-such-kind", "x.json"]
    with pytest.raises(SystemExit) as plain:
        main(argv)  # PA_NO_EVENTS is on here (conftest): the result without the log
    monkeypatch.delenv("PA_NO_EVENTS")
    monkeypatch.setenv("WIRE_EVENTS_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as logged:
        main(argv)
    assert logged.value.code == plain.value.code and "unknown schema" in plain.value.code
    (day,) = tmp_path.glob("*.jsonl")
    (line,) = [json.loads(x) for x in day.read_text().splitlines()]
    assert (line["step"], line["status"], line["err"]) == ("check", "fail", plain.value.code)

    code = "import sys; from wire import events\nfor i in range(200): events.emit('t', n={'w': sys.argv[1], 'i': i}, warn='x' * 3000)"
    env = {**os.environ, "WIRE_EVENTS_DIR": str(tmp_path / "two"), "PYTHONPATH": str(Path(__file__).parent.parent)}
    procs = [subprocess.Popen([sys.executable, "-c", code, w], env=env) for w in "ab"]
    assert [p.wait() for p in procs] == [0, 0]
    (two,) = (tmp_path / "two").glob("*.jsonl")
    rows = [json.loads(x) for x in two.read_text().splitlines()]  # a torn line would not parse
    assert sorted((r["n"]["w"], r["n"]["i"]) for r in rows) == sorted((w, i) for w in "ab" for i in range(200))
