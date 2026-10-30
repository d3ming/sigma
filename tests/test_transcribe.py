"""`sigma transcribe` around the edges: which Python it runs under, the lock, reusing a transcript, news last, the download retries."""
import io
import json
import os

import pytest
import requests

from sigma import fetch as fetch_mod
from sigma.cli import main
from sigma import whisper
from tests.helpers import LONG, ep, make_run, targs


def test_the_python_with_whisper_is_chosen_and_a_run_needs_one(monkeypatch, tmp_path):
    monkeypatch.delenv("SIGMA_PYTHON", raising=False)
    monkeypatch.setattr(fetch_mod, "has_whisper", lambda p: p == str(tmp_path / ".venv" / "bin" / "python"))
    monkeypatch.setattr(fetch_mod, "ROOT", tmp_path)
    monkeypatch.setattr(fetch_mod.Path, "exists", lambda self: True)
    assert fetch_mod.whisper_python() == str(tmp_path / ".venv" / "bin" / "python")
    monkeypatch.setattr(fetch_mod, "has_whisper", lambda p: False)
    with pytest.raises(SystemExit, match="no interpreter with mlx_whisper or faster_whisper"):
        fetch_mod.whisper_python()
    monkeypatch.undo()
    run = make_run(tmp_path / "r", [])
    monkeypatch.setattr(whisper, "available", lambda: False)
    with pytest.raises(SystemExit, match="neither mlx_whisper nor faster_whisper is importable"):
        fetch_mod.transcribe_run(targs(run))
    monkeypatch.setattr(whisper, "available", lambda: True)
    (run / "transcribe.lock").write_text("999999999")
    fetch_mod.transcribe_run(targs(run))  # a dead pid's lock is taken over
    (run / "transcribe.lock").write_text(str(os.getpid()))
    with pytest.raises(SystemExit, match="held by running pid"):
        fetch_mod.transcribe_run(targs(run))


def test_a_transcript_from_another_run_is_reused_and_news_is_whispered_last_or_not_at_all(monkeypatch, tmp_path):
    make_run(tmp_path / "2026-10-21-daily", [ep("rss:a", "Reducto on documents", "a16z"),
                                            ep("rss:b", "Halftime: AI trade", "halftime", "https://dts.podtrac.com/redirect.mp3/x.com/h1.mp3?t=1")], LONG)
    run = make_run(tmp_path / "2026-10-22", [ep("rss:a", "Reducto on documents", "a16z"),
                                            ep("rss:z", "Halftime: AI trade!", "halftime", "https://x.com/h1.mp3"),
                                            ep("rss:n", "Brand new", "a16z")])
    monkeypatch.setattr(whisper, "available", lambda: True)
    calls = []
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: calls.append(url) or (LONG, 180.0))
    fetch_mod.transcribe_run(targs(run))
    m = {e["episode_id"]: e for e in json.loads((run / "manifest.json").read_text())["episodes"]}
    assert calls == ["https://cdn.example/rss:n.mp3"]  # same title, or same audio behind a tracker: already transcribed
    assert all(e["has_transcript"] for e in m.values())
    assert "[0:00:10] word" in (run / m["rss:z"]["file"]).read_text()
    news = make_run(tmp_path / "news", [ep("rss:h", "Halftime", "cnbc-halftime"), ep("rss:x", "Deep dive", "no-priors")], **{"rss:h": {"news": True}})
    calls.clear()
    monkeypatch.setattr(whisper, "transcribe", lambda url, b: calls.append(url) or (LONG, 60.0))
    main(["transcribe", str(news), "--top", "0", "--people", ""])  # news shows are not whispered unless asked
    assert calls == ["https://cdn.example/rss:x.mp3"]
    main(["transcribe", str(news), "--top", "0", "--people", "", "--news"])
    assert calls == ["https://cdn.example/rss:x.mp3", "https://cdn.example/rss:h.mp3"]  # --news: after the others
    assert fetch_mod.is_news({"source": "CNBC Power Lunch"})


class Resp:
    def __init__(self, code, body=b"audio"):
        self.status_code, self.body = code, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def iter_content(self, n):
        yield self.body


def seq_get(*codes):
    it = iter(codes)

    def get(url, **kw):
        c = next(it)
        if isinstance(c, Exception):
            raise c
        return Resp(c)
    return get


def test_audio_downloads_retry_what_may_pass_and_give_up_on_what_will_not():
    sleeps, f = [], io.BytesIO()
    n = whisper.download("u", f, retries=3, backoff=1, sleep=sleeps.append, get=seq_get(503, requests.ConnectionError("x"), 429, 200))
    assert n == 4 and sleeps == [1, 2, 4] and f.getvalue() == b"audio"
    sleeps = []
    with pytest.raises(whisper.DownloadError) as ei:
        whisper.download("u", io.BytesIO(), retries=3, backoff=1, sleep=sleeps.append, get=seq_get(404))
    assert ei.value.attempts == 1 and not ei.value.transient and sleeps == [] and "404" in str(ei.value)
    with pytest.raises(whisper.DownloadError) as ei:
        whisper.download("u", io.BytesIO(), retries=2, backoff=0, sleep=lambda s: None, get=seq_get(500, 502, 504))
    assert ei.value.attempts == 3 and ei.value.errors == ["HTTPError 500", "HTTPError 502", "HTTPError 504"]
