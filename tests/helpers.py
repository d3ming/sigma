"""Fixtures shared across test files. Import from here, never from another test file."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import jsonschema

from wire import cli, fetch as fetch_mod
from wire.ingest import Episode

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
LONG = [{"start": i * 10, "speaker": None, "text": "word " * 100} for i in range(20)]
_SCHEMA = json.loads((Path(__file__).parent.parent / "schema" / "status.schema.json").read_text())
STATUS_SHAPE = jsonschema.validators.validator_for(_SCHEMA)(_SCHEMA)  # built once: jsonschema.validate re-checks the schema on every call
SIG = {"text": "t", "speaker": "Jane Placeholder", "timestamp": 75, "our_read": "r"}
REPORT = {"date": "2026-10-21", "title": "Podcast Intel: test", "run_dir": "runs/x", "key_insights": ["k1", "k2", "k3"],
          "essential": [{"episode_id": f"yt:{k}", "headline": "Jane on robots", "show": "Widget Show", "guests": "Host and Jane, CEO"}
                        for k in "abc"],
          "episodes": [{"episode_id": f"yt:{k}", "headline": "Jane on robots", "url": f"https://www.youtube.com/watch?v={k}",
                        "signal": [SIG, SIG, {**SIG, "timestamp": None}],
                        "sections": [{"title": "Demand", "body": "b", "claims": [{"text": "c", "speaker": "host", "timestamp": 3}]}]}
                       for k in "abc"]}


def targs(run, **kw):
    return SimpleNamespace(**{"run": str(run), "minutes": 600, "per_episode": None, "db": None, "force": False, "retry_errors": False,
                              "include_reruns": False, "min_transcript_chars": 5000, "news": True, **kw})


def ep(i, title, src="show", audio=None):
    return Episode(id=i, source_id=src, source_name=src.title(), tier=1, title=title, url="u", published_at=NOW,
                   audio_url=audio or f"https://cdn.example/{i}.mp3")


def make_run(d, eps, segs=None, **extra):
    d.mkdir(parents=True)
    rows = []
    for e in eps:
        r = fetch_mod.write_episode(d, e, segs, "whisper (3 min)" if segs else None)
        r.update(extra.get(e.id, {}))
        rows.append(r)
    (d / "manifest.json").write_text(json.dumps({"episodes": rows}))
    return d


def sandbox(tmp_path, monkeypatch):
    """A throwaway repo root for CLI journeys. wire.cli reads sources.yaml, people.yaml, show_links.yaml, runs/ and data/
    from its ROOT, so pointing ROOT at tmp_path keeps `main([...])` away from the real files."""
    (tmp_path / "sources.yaml").write_text("sources:\n  - {id: widget, name: Widget Show, tier: 1, rss: 'https://feed.invalid/w'}\n"
                                          "  - {id: gadget, name: Gadget Hour, tier: 1, rss: 'https://feed.invalid/g'}\n")
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "people.yaml").write_text("people:\n  - {name: Jane Placeholder, role: CEO, priority: core}\n")
    (tmp_path / "show_links.yaml").write_text("{}\n")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path


def spoken(lines=None, minutes=30, filler="filler", every=60):
    """A transcript with a segment every `every` seconds that ends just before `minutes` (1740 s by default): filler words
    except the {second: text} given."""
    lines = lines or {}
    return [{"start": t, "speaker": None, "text": lines.get(t, f"{filler} " * every).strip()} for t in range(0, minutes * 60, every)]


def no_web(monkeypatch, routes=None):
    """urllib.request.urlopen answers from {url substring: body}; any other URL fails like a dead network."""
    import io
    import urllib.error
    import urllib.request

    def urlopen(req, timeout=None):
        url = getattr(req, "full_url", req)
        for part, body in (routes or {}).items():
            if part in url:
                return io.BytesIO(body if isinstance(body, bytes) else body.encode())
        raise urllib.error.URLError(f"no network in tests: {url}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
