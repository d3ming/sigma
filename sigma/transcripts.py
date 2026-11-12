"""Which transcript of an episode to trust: whether a copy is complete, whether two copies are the same media, the
fullest complete copy among them, and the record a score keeps of the transcript it was made on (theta#93)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

LENGTH_TOLERANCE = 0.02
WHISPER_SHORT_SECONDS = 120
MATERIAL_SECONDS = 60
MATERIAL_SHARE = 0.05
LOW_COVERAGE = 0.9
LEGACY = "legacy archive, not a source"
STAMP = re.compile(r"^\[(\d+(?::\d\d){1,2})\]", re.M)
WHISPER_MINUTES = re.compile(r"^whisper .*\((\d+) min")

TRACKER = re.compile(r"^(dts\.podtrac\.com/redirect\.mp3/|www\.podtrac\.com/pts/redirect\.mp3/|chtbl\.com/track/[^/]+/|"
                     r"pdst\.fm/e/|prfx\.byspotify\.com/e/|tracking\.swap\.fm/track/[^/]+/|claritaspod\.com/measure/|"
                     r"arttrk\.com/p/[^/]+/|verifi\.podscribe\.com/rss/p/|pfx\.vpixl\.com/[^/]+/|mgln\.ai/e/[^/]+/|op3\.dev/e/)")


def norm_audio(u: str | None) -> str:
    """Host + path of the enclosure with query and tracking-redirect prefixes (podtrac, swap.fm, ...) stripped."""
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u.split("?", 1)[0].lower())
    while (m := TRACKER.match(u)):
        u = re.sub(r"^https?://", "", u[m.end():])
    return u


def video(row: dict) -> str | None:
    return row.get("youtube_id") or (row["episode_id"][3:] if row["episode_id"].startswith("yt:") else None)


def body(md: str) -> str:
    return md.partition("## Transcript")[2]


def end_seconds(md: str) -> int | None:
    stamps = STAMP.findall(body(md))
    if not stamps:
        return None
    sec = 0
    for part in stamps[-1].split(":"):
        sec = sec * 60 + int(part)
    return sec


def media_seconds(row: dict) -> float | None:
    """Length of the media the transcript was made from: what whisper measured, else what the feed declared."""
    return row.get("media_seconds") or row.get("duration") or None


def incomplete(row: dict) -> str | None:
    if row.get("transcript_complete") is not False:
        return None
    media = media_seconds(row)
    return f"partial transcript ({row.get('transcript_minutes')} of {round(media / 60) if media else '?'} min)"


def _label_short(row: dict) -> tuple[int, float, float] | None:
    """(label minutes, media seconds, share of the media the transcript reaches) for a transcript made before completeness
    was recorded whose whisper label names fewer minutes than the media has."""
    if "transcript_complete" in row:
        return None
    m = WHISPER_MINUTES.match(row.get("transcript_source") or "")
    media = media_seconds(row)
    if not (m and media and int(m.group(1)) * 60 < media - WHISPER_SHORT_SECONDS):
        return None
    reach = (row.get("transcript_minutes") or int(m.group(1))) * 60 / media
    return int(m.group(1)), media, reach


def whisper_short(row: dict) -> str | None:
    """A legacy whisper transcript that ends well short of its media: the budget cut it. A feed often declares more time
    than the audio has, so a label a few minutes short is not evidence of a cut on its own."""
    short = _label_short(row)
    if short and short[2] < LOW_COVERAGE:
        return f"whisper stopped at {short[0]} of {round(short[1] / 60)} min"
    return None


def unverified_length(row: dict) -> str | None:
    """A legacy whisper label a few minutes short of the feed's length, reaching LOW_COVERAGE or more: not partial."""
    short = _label_short(row)
    if short and short[2] >= LOW_COVERAGE:
        return f"unverified length (whisper {short[0]} of {round(short[1] / 60)} min)"
    return None


def partial(row: dict) -> str | None:
    return incomplete(row) or whisper_short(row)


def same_media(a: dict, b: dict) -> bool:
    """Same episode, same enclosure or YouTube video, and lengths within LENGTH_TOLERANCE wherever both are known: an
    ad-shifted enclosure or a different video is different media even under one episode id."""
    if a["episode_id"] != b["episode_id"]:
        return False
    audio, other = norm_audio(a.get("audio_url")), norm_audio(b.get("audio_url"))
    keyed = audio or other or video(a) or video(b)
    if keyed and not ((audio and audio == other) or (video(a) and video(a) == video(b))):
        return False
    for k in ("media_seconds", "duration"):
        x, y = a.get(k), b.get(k)
        if x and y and abs(x - y) > LENGTH_TOLERANCE * max(x, y):
            return False
    return True


def record(path: Path, row: dict) -> dict | None:
    """What a score keeps of the episode file it was made on; sha256 is of the whole file, as editor.json's source_sha256."""
    if not path.is_file() or (end := end_seconds(path.read_text(errors="replace"))) is None:
        return None
    media = media_seconds(row)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "end_seconds": end,
            "media_seconds": round(media) if media else None}


def check(stored: dict | None, current: dict | None) -> str:
    """verified | mismatch | unverifiable: does a score's stored record describe the transcript there is now."""
    if not stored:
        return "unverifiable"
    if not current:
        return "mismatch"
    if stored["sha256"] == current["sha256"]:
        return "verified"
    moved = abs(current["end_seconds"] - stored["end_seconds"]) > max(MATERIAL_SECONDS, MATERIAL_SHARE * stored["end_seconds"])
    return "mismatch" if moved else "verified"


def fuller(longer: int, shorter: int) -> bool:
    return longer > shorter * (1 + MATERIAL_SHARE) + MATERIAL_SECONDS


@dataclass
class Copy:
    path: Path
    row: dict
    end: int
    legacy: bool = False

    @property
    def run(self) -> str:
        return self.path.parent.name


def copy_of(run_dir: Path, row: dict, legacy: bool = False) -> Copy | None:
    p = run_dir / row["file"] if row.get("file") else None
    end = end_seconds(p.read_text(errors="replace")) if p and p.is_file() else None
    return Copy(p, row, end, legacy) if end is not None else None


def choose(copies: list[Copy], target: dict | None = None) -> tuple[Copy | None, list[tuple[Copy, str]]]:
    """The fullest complete copy, preferring the target's own media, and every other copy with why it was passed over.
    Copies come oldest run first, so a tie keeps the oldest."""
    skipped, eligible = [], []
    for c in copies:
        why = (LEGACY if c.legacy else partial(c.row)
               or ("different media" if target and c.row["episode_id"] == target["episode_id"] and not same_media(target, c.row) else None))
        (skipped if why else eligible).append((c, why) if why else c)
    if not eligible:
        return None, skipped
    best = max(eligible, key=lambda c: (bool(target) and same_media(target, c.row), c.end))
    for c in eligible:
        if c is not best:
            skipped.append((c, "different media" if not same_media(best.row, c.row) else "shorter" if c.end < best.end else "same length"))
    return best, skipped


def rows_of(runs: Path, episode_id: str) -> list[tuple[Path, dict]]:
    """Every manifest row of the episode under a runs folder, oldest run first."""
    out = []
    for mp in sorted(runs.glob("*/manifest.json")):
        try:
            rows = json.loads(mp.read_text()).get("episodes", [])
        except (OSError, ValueError):
            continue
        out += [(mp.parent, r) for r in rows if r.get("episode_id") == episode_id]
    return out


def runs_copies(rows: list[tuple[Path, dict]], legacy: bool = False) -> list[Copy]:
    return [c for d, r in rows if (c := copy_of(d, r, legacy))]


def legacy_roots(root: Path) -> list[Path]:
    """`legacy_transcripts` in <data root>/operator.json: run folders from before this data root, never a source."""
    try:
        conf = json.loads((root / "operator.json").read_text())
    except (OSError, ValueError):
        return []
    return [(root / p).resolve() for p in conf.get("legacy_transcripts") or []]


def minutes(seconds: float | None) -> float | None:
    return round(seconds / 60, 1) if seconds else None


def locate(root: Path, episode_id: str) -> dict:
    """`sigma transcript`: the fullest complete copy under <data root>/runs of the media the newest run lists, and every
    other copy with why it was not chosen."""
    rows = rows_of(root / "runs", episode_id)
    best, skipped = choose(runs_copies(rows), rows[-1][1] if rows else None)
    for legacy in legacy_roots(root):
        skipped += [(c, LEGACY) for c in runs_copies(rows_of(legacy, episode_id), legacy=True)]
    every = ([best] if best else []) + [c for c, _ in skipped]

    def item(c: Copy, why: str | None = None) -> dict:
        return {"path": str(c.path), "run": c.run, "minutes": minutes(c.end), "media_minutes": minutes(media_seconds(c.row)),
                "transcript_source": c.row.get("transcript_source"), **({"reason": why} if why else {})}

    return {"episode_id": episode_id, "title": every[0].row.get("title") if every else None,
            "chosen": item(best) if best else None, "skipped": [item(c, why) for c, why in skipped]}


def render(found: dict) -> str:
    c = found["chosen"]
    lines = [f"{found['episode_id']}  {found['title'] or 'no copy in runs/'}",
             f"use: {c['path']}  {c['minutes']} of {c['media_minutes'] or '?'} min" if c else "no complete transcript in runs/"]
    lines += [f"skipped: {s['path']}  {s['minutes']} min  {s['reason']}" for s in found["skipped"]]
    return "\n".join(lines)
