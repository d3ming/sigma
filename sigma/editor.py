from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

from . import report
from .fetch import segments_from_md
from .ranked import private_hits

FILE = "editor.json"
FIELDS = ("key_insights", "dense_summary", "context", "overview")


def load(run_dir: str | Path) -> dict[str, dict]:
    run_dir = Path(run_dir).resolve()
    path = run_dir / FILE
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError("editor.json must be a regular source file")
    data = json.loads(path.read_text())
    schema = json.loads((Path(__file__).resolve().parent.parent / "schema" / "editor.schema.json").read_text())
    jsonschema.validate(data, schema)
    if hits := private_hits(data):
        raise ValueError(f"editor.json looks private ({hits})")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    rows = {row["episode_id"]: row for row in manifest.get("episodes", [])}
    out = {}
    for episode in data["episodes"]:
        eid = episode["episode_id"]
        if eid in out or eid not in rows:
            raise ValueError(f"editor: duplicate or unknown episode {eid}")
        row = rows[eid]
        source = (run_dir / row.get("file", "")).resolve()
        if not source.is_file() or run_dir not in source.parents or not row.get("has_transcript"):
            raise ValueError(f"editor: {eid}: readable source transcript required")
        if hashlib.sha256(source.read_bytes()).hexdigest() != episode["source_sha256"]:
            raise ValueError(f"editor: {eid}: source transcript fingerprint differs")
        segs = segments_from_md(source.read_text())
        last, grams, labels = report._load_transcript(run_dir, row)
        if last is None or not segs:
            raise ValueError(f"editor: {eid}: no timestamped source transcript")
        for field in ("context", "overview"):
            if copied := report._longest_copy(episode.get(field) or "", grams):
                raise ValueError(f"editor: {eid} {field}: {len(copied)} consecutive source words copied")
        numbers = report.spoken_numbers(report._stream(segs))
        previous = -1
        for field in ("key_insights", "dense_summary"):
            for i, item in enumerate(episode[field]):
                start, end = item["start"], item["end"]
                where = f"editor: {eid} {field}[{i}]"
                if start > end or end > last + report.TS_SLACK:
                    raise ValueError(f"{where}: source interval is outside the transcript")
                if field == "dense_summary":
                    if start < previous:
                        raise ValueError(f"{where}: summary intervals must be chronological")
                    previous = start
                if field == "key_insights" and (actual := report._speaker_error(item["speaker"], start, labels)):
                    raise ValueError(f"{where}: speaker does not match transcript label {actual!r}")
                text = " ".join(item.get(k) or "" for k in ("text", "why_it_matters"))
                prose = " ".join(item.get(k) or "" for k in ("title", "text", "why_it_matters", "inference"))
                if copied := report._longest_copy(prose, grams):
                    raise ValueError(f"{where}: {len(copied)} consecutive source words copied")
                near = {key for timestamp, key in numbers if start - 5 <= timestamp <= end + 5}
                for key, number in report.cite_numbers(text):
                    if key not in near:
                        raise ValueError(f"{where}: number {number} is not spoken in the cited source interval")
        out[eid] = {field: episode[field] for field in FIELDS if field in episode}
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate a run's optional editor.json against its exact transcript sources.")
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    checked = load(args.run)
    print(f"[editor] {len(checked)} episodes; "
          f"{sum(len(e['key_insights']) for e in checked.values())} key insights; "
          f"{sum(len(e['dense_summary']) for e in checked.values())} chronological sections validated")
