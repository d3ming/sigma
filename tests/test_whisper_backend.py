import sys
from types import SimpleNamespace

from wire import whisper


def force_platform(monkeypatch, system, machine, modules):
    monkeypatch.setattr(whisper.sys, "platform", system)
    monkeypatch.setattr(whisper.platform, "machine", lambda: machine)
    monkeypatch.setattr(whisper, "has_module", lambda name: name in modules)


def test_auto_picks_mlx_only_on_apple_silicon_with_mlx(monkeypatch):
    monkeypatch.setenv("PA_WHISPER_BACKEND", "auto")
    force_platform(monkeypatch, "darwin", "arm64", {"mlx_whisper", "faster_whisper"})
    assert whisper.backend() == "mlx" and whisper.available()
    force_platform(monkeypatch, "darwin", "arm64", {"faster_whisper"})
    assert whisper.backend() == "faster" and whisper.available()
    force_platform(monkeypatch, "linux", "x86_64", {"mlx_whisper", "faster_whisper"})
    assert whisper.backend() == "faster"
    force_platform(monkeypatch, "darwin", "x86_64", {"mlx_whisper"})
    assert whisper.backend() == "faster" and not whisper.available()  # Intel Mac: no MLX, and faster is missing
    force_platform(monkeypatch, "darwin", "arm64", {"mlx_whisper"})
    assert whisper.available()  # mlx alone is enough


def _mlx_fakes(monkeypatch, duration, segs=None):
    monkeypatch.setenv("PA_WHISPER_BACKEND", "mlx")
    seen = {"paths": [], "trim": []}
    segs = segs or [{"start": 0.0, "end": 5.0, "text": "hi"}]

    def fake_transcribe(path, **kw):
        seen["paths"].append(path)
        seen.update(kw)
        return {"segments": segs}

    def fake_trim(path, limit):
        seen["trim"].append((path, limit))
        return "/tmp/trimmed.wav"

    monkeypatch.setitem(sys.modules, "mlx_whisper", SimpleNamespace(transcribe=fake_transcribe))
    monkeypatch.setattr(whisper, "audio_seconds", lambda p: duration)
    monkeypatch.setattr(whisper, "trim_audio", fake_trim)
    monkeypatch.setattr(whisper.os, "unlink", lambda p: seen.setdefault("unlinked", []).append(p))
    return seen


def test_mlx_cuts_at_the_budget_and_trims_the_audio_only_when_it_is_shorter(monkeypatch):
    segs = [{"start": 0.0, "end": 30.0, "text": " one "}, {"start": 90.0, "end": 120.0, "text": "two"},
            {"start": 200.0, "end": 230.0, "text": "three"}]
    seen = _mlx_fakes(monkeypatch, 230.0, segs)
    monkeypatch.setattr(whisper, "trim_audio", lambda p, l: None)  # trim failed: whole file, output still cut at budget
    b = whisper.Budget(2)  # 120 s
    out, used = whisper.transcribe_file("x.mp3", b)
    assert out == [{"start": 0.0, "speaker": None, "text": "one"}, {"start": 90.0, "speaker": None, "text": "two"}]
    assert used == 120 and b.used == 120 and seen["paths"] == ["x.mp3"]
    assert seen["language"] == "en" and seen["condition_on_previous_text"] is False
    monkeypatch.setattr(whisper, "audio_seconds", lambda p: None)  # no ffprobe: fall back to the last segment end
    assert whisper.transcribe_file("x.mp3", whisper.Budget(60))[1] == 230.0
    seen = _mlx_fakes(monkeypatch, 3 * 3600)
    out, used = whisper.transcribe_file("long.mp3", whisper.Budget(5))
    assert seen["trim"] == [("long.mp3", 300)] and seen["paths"] == ["/tmp/trimmed.wav"]
    assert seen["unlinked"] == ["/tmp/trimmed.wav"] and used == 300 and out
    seen = _mlx_fakes(monkeypatch, 600)
    whisper.transcribe_file("short.mp3", whisper.Budget(20))
    assert seen["trim"] == [] and seen["paths"] == ["short.mp3"]
