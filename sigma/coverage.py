"""Refuse a publication that silently drops data: an episode the live site serves, or a scored run with no published copy.

Anything left out on purpose is named with a reason in <data root>/withheld.json:
{"episodes": {"<episode id>": "<reason>"}, "runs": {"<run name>": "<reason>"}}
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .paths import data_root

WITHHELD = "withheld.json"


def withheld(root: Path) -> dict:
    path = root / WITHHELD
    if not path.exists():
        return {"episodes": {}, "runs": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = [k for k in ("episodes", "runs") if not isinstance(data.get(k, {}), dict)
           or any(not isinstance(v, str) or not v.strip() for v in data.get(k, {}).values())]
    if bad or set(data) - {"episodes", "runs"}:
        raise ValueError(f"{path}: expected {{\"episodes\": {{id: reason}}, \"runs\": {{name: reason}}}} with a reason for each")
    return {"episodes": data.get("episodes", {}), "runs": data.get("runs", {})}


def episode_ids(doc: dict) -> set[str]:
    """Ids a build serves: its episodes, and the ids it merged into one of them (the site redirects those pages)."""
    ids = {e["episode_id"] for e in doc.get("episodes", [])}
    return ids | {old for old, kept in (doc.get("merged") or {}).items() if kept in ids}


def live_episodes(base_url: str, timeout: float = 30) -> set[str] | None:
    """Episode ids the live site serves; None only when the site has never served episodes.json (a first publication)."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/episodes.json", timeout=timeout) as r:
            return episode_ids(json.load(r))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def dropped_episodes(live: set[str] | None, build: set[str], kept_out: dict) -> list[str]:
    return sorted((live or set()) - build - set(kept_out))


def unpublished_runs(root: Path, kept_out: dict) -> list[str]:
    runs, published = root / "runs", root / "published"
    scored = [d.name for d in sorted(runs.iterdir()) if d.is_dir()
              and any((d / f).exists() for f in ("ranked.json", "scores.json"))] if runs.is_dir() else []
    return [r for r in scored if not (published / r).is_dir() and r not in kept_out]


def check(root: Path, build_episodes: Path, base_url: str) -> list[str]:
    kept = withheld(root)
    problems = []
    try:
        live = live_episodes(base_url)
    except (OSError, ValueError) as exc:
        return [f"could not read the live episode list at {base_url}/episodes.json ({exc}); nothing proves this build keeps it"]
    gone = dropped_episodes(live, episode_ids(json.loads(build_episodes.read_text(encoding="utf-8"))), kept["episodes"])
    if gone:
        problems.append(f"{len(gone)} episode(s) the live site serves are missing from this build: {', '.join(gone[:20])}"
                        + (" ..." if len(gone) > 20 else ""))
    if left := unpublished_runs(root, kept["runs"]):
        problems.append(f"{len(left)} scored run(s) have no published copy: {', '.join(left[:20])}" + (" ..." if len(left) > 20 else ""))
    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sigma coverage", description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, type=Path, help="the new build's episodes.json")
    p.add_argument("--base-url", required=True, help="the live site whose episodes this build must keep")
    args = p.parse_args(argv)
    root = data_root()
    problems = check(root, args.build, args.base_url)
    for line in problems:
        print(f"[coverage] {line}", file=sys.stderr)
    if problems:
        print(f"[coverage] publish it, or name it with a reason in {root / WITHHELD}", file=sys.stderr)
        return 1
    print("[coverage] build keeps every live episode and every scored run is published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
