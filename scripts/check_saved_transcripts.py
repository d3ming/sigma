import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sigma.transcripts import end_seconds


def git(*args):
    return subprocess.check_output(["git", *args])


def check(root: Path, prefix: Path, main: str, candidate: str) -> None:
    scopes = [str(prefix / name) for name in ("published", "runs")]
    entries = git("ls-tree", "-rz", candidate, "--", *scopes).split(b"\0")
    blobs = {}
    for entry in filter(None, entries):
        metadata, path = entry.split(b"\t", 1)
        mode, _, oid = metadata.split()
        blobs[Path(os.fsdecode(path)).relative_to(prefix)] = (mode, oid.decode())
    changed_runs = {
        public.parent.name for public in (root / "published").glob("*/episodes.json")
        if public.relative_to(root) not in blobs
    }
    changes = git("diff", "--no-renames", "--name-only", "-z", main, candidate, "--", *scopes)
    for name in filter(None, changes.split(b"\0")):
        parts = Path(os.fsdecode(name)).relative_to(prefix).parts
        if len(parts) >= 3:
            changed_runs.add(parts[1])
    if not changed_runs:
        return
    algorithm = git("rev-parse", "--show-object-format").decode().strip()

    def saved(path):
        relative = path.relative_to(root)
        mode, oid = blobs.get(relative, (None, None))
        if not path.is_symlink() and mode in {b"100644", b"100755"}:
            content = path.read_bytes()
            blob = hashlib.new(algorithm, f"blob {len(content)}\0".encode() + content).hexdigest()
            if oid == blob:
                return content
        raise ValueError(f"{relative} is missing or differs in the private Git save. "
                         "Check Git ignores and filters before retrying.")

    for name in sorted(changed_runs):
        relative = Path("published") / name / "episodes.json"
        public = root / relative
        if relative not in blobs and not public.exists() and not public.is_symlink():
            continue
        episode_ids = {row["episode_id"] for row in json.loads(saved(public)) if row.get("has_transcript")}
        if not episode_ids:
            continue
        run = root / "runs" / name
        manifest_bytes = saved(run / "manifest.json")
        episodes = {row["episode_id"]: row for row in json.loads(manifest_bytes)["episodes"]}
        for episode_id in sorted(episode_ids):
            row = episodes.get(episode_id, {})
            source = run / (row.get("file") or "")
            if not row.get("has_transcript") or run not in source.resolve().parents:
                raise ValueError(f"{run.name}: {episode_id} has no source path inside its run")
            content = saved(source)
            if end_seconds(content.decode("utf-8")) is None:
                raise ValueError(f"{source.relative_to(root)} has no timestamped transcript")


if __name__ == "__main__":
    try:
        check(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        sys.exit(f"[data] refusing to save a publication without its exact transcript sources: {exc}")
