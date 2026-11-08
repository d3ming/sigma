"""Refuse a publication that silently drops data: an episode the site already serves, or a scored episode the build leaves out.

The baseline is every episode list readers have: the live site's and the last publication this checkout deployed.
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

from .links import yt_id
from .paths import data_root
from .publication_policy import MIN_SCORE
from .site import one_release

WITHHELD = "withheld.json"
LISTS = ("episodes.json", "social/episodes.json")
SCORED = ("ranked.json", "scores.json")
SOCIAL_SCORED = "scores-influencer.json"


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


def site_lists(read) -> dict:
    """{"episodes": {id: record}, "merged": {old id: kept id}} from a site's lists; read(name) returns one parsed list."""
    episodes, merged = {}, {}
    for name in LISTS:
        doc = read(name)
        episodes.update({e["episode_id"]: e for e in doc["episodes"]})
        merged.update(doc.get("merged") or {})
    return {"episodes": episodes, "merged": merged}


def folder_lists(static: Path) -> dict:
    return site_lists(lambda name: json.loads((static / name).read_text(encoding="utf-8")))


def live_lists(base_url: str, timeout: float = 30) -> dict | None:
    """The live site's lists; None when it serves no episodes.json at all (404). Any other failure raises."""
    def read(name):
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/{name}", timeout=timeout) as r:
            return json.load(r)
    try:
        read(LISTS[0])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return site_lists(read)


def video(record: dict) -> str | None:
    eid = str(record.get("episode_id") or "")
    return eid[3:] if eid.startswith("yt:") else yt_id(record.get("youtube_url"))


def served(eid: str, known: dict, build: dict) -> dict | None:
    """The build's record for eid: its own, or the episode it merged eid into when that is the same release by what the
    baseline or the run recorded about eid (known: its show, published, youtube_url), not by the build's word alone."""
    if eid in build["episodes"]:
        return build["episodes"][eid]
    kept = build["episodes"].get(build["merged"].get(eid))
    if not kept:
        return None
    known = {**known, "show": known.get("show") or known.get("source")}
    return kept if (not known.get("youtube_url") or video(known) == video(kept)) and one_release(known, kept) else None


def thinned(before: dict, after: dict) -> bool:
    """A served episode lost its page, or all its claims."""
    return bool(before.get("page")) and not after.get("page") or bool(before.get("claims")) and not after.get("claims")


def baseline(base_url: str, previous: Path | None, first: bool) -> tuple[dict, list[str], list[str]]:
    """({id: record} readers have, notes, problems). Fails closed: some baseline must be read, unless first is set, and first is
    refused once any baseline exists."""
    have, notes = {}, []
    try:
        live = live_lists(base_url)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        live, unreadable = None, f"could not read the live episode lists at {base_url} ({exc})"
    else:
        unreadable = ""
    if live:
        have.update(live["episodes"])
    if previous:
        try:
            have.update(folder_lists(previous)["episodes"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {}, notes, [f"could not read the last deployed publication's episode lists in {previous} ({exc})"]
    if unreadable and not previous and not first:
        return {}, notes, [f"{unreadable}, and no deployed publication is recorded; nothing proves this build keeps them. "
                           "If this is the site's first publication, say so with FIRST_PUBLICATION=1"]
    if unreadable and not previous:
        notes.append(f"first publication: {unreadable}, and no deployed publication is recorded")
        return have, notes, []
    if unreadable:
        notes.append(f"{unreadable}; compared against the last deployed publication only")
    if live is None and previous and not unreadable:
        notes.append(f"{base_url} serves no episodes.json; compared against the last deployed publication only")
    if live is None and not previous and not unreadable:
        if not first:
            return {}, notes, [f"{base_url} serves no episodes.json and no deployed publication is recorded; "
                               "if this is the site's first publication, say so with FIRST_PUBLICATION=1"]
        notes.append("first publication: no baseline to compare against")
    elif first:
        return {}, notes, ["FIRST_PUBLICATION=1, but the site already serves episodes"]
    return have, notes, []


def listed_by_site(e, social: bool) -> bool:
    """A scored record the site must list: every interview score; a Social score at the site's floor (MIN_SCORE) with claims,
    since the Social list shows only episodes with a page and claims always give one."""
    return isinstance(e, dict) and isinstance(e.get("score"), int) and (not social or e["score"] >= MIN_SCORE and bool(e.get("claims")))


def scored_runs(root: Path) -> dict[str, dict]:
    """{run name: {episode id: scored record}} for every run in runs/ with a ranking or scores."""
    out = {}
    for d in sorted((root / "runs").iterdir()) if (root / "runs").is_dir() else []:
        if files := [d / name for name in (*SCORED, SOCIAL_SCORED) if (d / name).is_file()]:
            out[d.name] = {e["episode_id"]: e for f in files for e in json.loads(f.read_text(encoding="utf-8")).get("episodes") or []
                           if listed_by_site(e, f.name == SOCIAL_SCORED)}
    return out


def listed(ids: list[str]) -> str:
    return ", ".join(ids[:20]) + (" ..." if len(ids) > 20 else "")


def check(root: Path, build_static: Path, base_url: str, previous: Path | None = None, first: bool = False) -> tuple[list[str], list[str]]:
    """(problems, notes) for the build in build_static."""
    kept = withheld(root)
    have, notes, problems = baseline(base_url, previous, first)
    if problems:
        return problems, notes
    build = folder_lists(build_static)
    now = {e: served(e, rec, build) for e, rec in have.items() if e not in kept["episodes"]}
    if gone := sorted(e for e, rec in now.items() if rec is None):
        problems.append(f"{len(gone)} episode(s) the site serves are missing from this build: {listed(gone)}")
    if thin := sorted(e for e, rec in now.items() if rec is not None and thinned(have[e], rec)):
        problems.append(f"{len(thin)} episode(s) the site serves lose their page or every claim in this build: {listed(thin)}")
    unpublished = []
    for run, eps in scored_runs(root).items():
        if run in kept["runs"]:
            continue
        if not (root / "published" / run).is_dir():
            unpublished.append(run)
        elif left := sorted(e for e, rec in eps.items() if e not in kept["episodes"] and not served(e, rec, build)):
            problems.append(f"run {run}: {len(left)} scored episode(s) are missing from this build: {listed(left)}")
    if unpublished:
        problems.append(f"{len(unpublished)} scored run(s) have no published copy: {listed(unpublished)}")
    if merged := {o: k for o, k in build["merged"].items() if o in have}:
        notes.append(f"{len(merged)} served id(s) merged into another episode: " + ", ".join(f"{o} -> {k}" for o, k in sorted(merged.items())))
    return problems, notes


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sigma coverage", description=__doc__.splitlines()[0])
    p.add_argument("--build", required=True, type=Path, help="the new build's static folder (holds episodes.json and social/)")
    p.add_argument("--base-url", required=True, help="the live site whose episodes this build must keep")
    p.add_argument("--previous", type=Path, help="the static folder of the last publication this checkout deployed")
    p.add_argument("--first-publication", action="store_true", help="the site has never been published; refused once it has")
    args = p.parse_args(argv)
    root = data_root()
    problems, notes = check(root, args.build, args.base_url, args.previous, args.first_publication)
    for line in notes:
        print(f"[coverage] {line}")
    for line in problems:
        print(f"[coverage] {line}", file=sys.stderr)
    if problems:
        print(f"[coverage] publish it, or name it with a reason in {root / WITHHELD}", file=sys.stderr)
        return 1
    print("[coverage] build keeps every served episode and every scored episode")
    return 0


if __name__ == "__main__":
    sys.exit(main())
