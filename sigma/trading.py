from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .ranked import private_hits

PATH = "/trading/"
TITLE = "Trading techniques"
SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "trading.schema.json"


def load(published: Path) -> dict | None:
    path = published / "trading.json"
    if not path.is_file():
        return None
    catalog = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    if error := next(validator.iter_errors(catalog), None):
        location = "/".join(map(str, error.absolute_path))
        raise ValueError(f"trading.json: invalid catalog at {location or '/'}")
    if private_hits(catalog):
        raise ValueError("trading.json: content looks private")

    sections = catalog["sections"]
    videos = [video for section in sections for video in section["videos"]]
    durations = {video["id"]: video["duration"] for video in videos}
    if len(durations) != len(videos):
        raise ValueError("trading.json: video IDs must be unique")
    if len({section["id"] for section in sections}) != len(sections):
        raise ValueError("trading.json: section IDs must be unique")
    if len({playlist["id"] for playlist in catalog["playlists"]}) != len(catalog["playlists"]):
        raise ValueError("trading.json: playlist IDs must be unique")
    for section in sections:
        for clip in section["clips"]:
            if clip["video"] not in durations or clip["seconds"] >= durations[clip["video"]]:
                raise ValueError(f"trading.json: invalid source clip for {section['id']}")
    return catalog


def watch(video_id: str, seconds: int | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    return url if seconds is None else f"{url}&t={seconds}s"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"
