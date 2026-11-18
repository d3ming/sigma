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
        if mode in {b"100644", b"100755"}:
            blobs[Path(os.fsdecode(path)).relative_to(prefix)] = oid.decode()
    changed_runs = {
        path.parts[1] for name in git("diff", "--no-renames", "--name-only", "-z", main, candidate, "--", *scopes).split(b"\0")
        if name and len((path := Path(os.fsdecode(name)).relative_to(prefix)).parts) >= 3
    }
    algorithm = git("rev-parse", "--show-object-format").decode().strip()

    def saved(path, content):
        blob = hashlib.new(algorithm, f"blob {len(content)}\0".encode() + content).hexdigest()
        if path.is_symlink() or blobs.get(path.relative_to(root)) != blob:
            raise ValueError(f"{path.relative_to(root)} is missing or differs in the private Git save. "
                             "Check Git ignores and filters before retrying.")

    for public in sorted((root / "published").glob("*/episodes.json")):
        public_bytes = public.read_bytes()
        episode_ids = {row["episode_id"] for row in json.loads(public_bytes) if row.get("has_transcript")}
        if not episode_ids:
            continue
        saved(public, public_bytes)
        run = root / "runs" / public.parent.name
        manifest = run / "manifest.json"
        manifest_bytes = manifest.read_bytes()
        saved(manifest, manifest_bytes)
        episodes = {row["episode_id"]: row for row in json.loads(manifest_bytes)["episodes"]}
        for episode_id in sorted(episode_ids):
            row = episodes.get(episode_id, {})
            source = run / (row.get("file") or "")
            if not row.get("has_transcript") or run not in source.resolve().parents:
                raise ValueError(f"{run.name}: {episode_id} has no source path inside its run")
            if not source.is_file():
                if run.name not in changed_runs and source.relative_to(root) not in blobs:
                    continue
                raise ValueError(f"{source.relative_to(root)} is missing from the source run")
            content = source.read_bytes()
            saved(source, content)
            if run.name in changed_runs and end_seconds(content.decode("utf-8", errors="replace")) is None:
                raise ValueError(f"{source.relative_to(root)} has no timestamped transcript")


if __name__ == "__main__":
    try:
        check(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        sys.exit(f"[data] refusing to save a publication without its exact transcript sources: {exc}")
