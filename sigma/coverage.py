"""Refuse a publication that silently drops data: an episode the site already serves, or a scored episode the build leaves out.

The baseline is every episode list readers have: the live site's and the last publication this checkout deployed.
Anything left out on purpose is named with a reason in <data root>/withheld.json:
{"episodes": {"<episode id>": "<reason>"}, "runs": {"<run name>": "<reason>"}}
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .links import yt_id
from .paths import data_root
from .publication_policy import MIN_SCORE
from .site import episode_scores, one_release, run_date, scored_here

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


def richer(a: dict, b: dict) -> dict:
    """One episode's baseline from two records of it: a page if either has one, the larger claim count."""
    return {**b, **a, "page": a.get("page") or b.get("page"), "claims": max(a.get("claims") or 0, b.get("claims") or 0)}


def baseline(base_url: str, previous: Path | None, first: bool) -> tuple[dict, list[str], list[str]]:
    """({id: record} readers have, notes, problems). Fails closed: some baseline must be read. FIRST_PUBLICATION applies only
    when nothing is published: no deployment recorded, and the live site has no episodes.json (404) or does not answer."""
    have, notes = {}, []
    live, absent, failure = None, "", ""
    try:
        live = live_lists(base_url)
    except urllib.error.HTTPError as exc:
        failure = f"the live site at {base_url} answered, but not with its episode lists ({exc})"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.gaierror, ConnectionRefusedError)):
            absent = f"nothing answers at {base_url} ({exc.reason})"
        else:
            failure = f"could not read the live episode lists at {base_url} ({exc.reason})"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failure = f"could not read the live episode lists at {base_url} ({type(exc).__name__}: {exc})"
    if live is None and not (absent or failure):
        absent = f"{base_url} serves no episodes.json"
    have.update((live or {}).get("episodes", {}))
    if previous:
        try:
            for eid, rec in folder_lists(previous)["episodes"].items():
                have[eid] = richer(have[eid], rec) if eid in have else rec
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {}, notes, [f"could not read the last deployed publication's episode lists in {previous} ({exc})"]
    if first and (live is not None or previous):
        return {}, notes, ["FIRST_PUBLICATION=1, but the site already serves episodes"]
    if failure and not previous:
        return {}, notes, [f"{failure}, and no deployed publication is recorded; nothing proves this build keeps them "
                           "(FIRST_PUBLICATION=1 applies only when the live site has no episodes.json or does not answer)"]
    if (failure or absent) and previous:
        notes.append(f"{failure or absent}; compared against the last deployed publication only")
    if absent and not previous:
        if not first:
            return {}, notes, [f"{absent} and no deployed publication is recorded; "
                               "if this is the site's first publication, say so with FIRST_PUBLICATION=1"]
        notes.append(f"first publication: {absent}")
    return have, notes, []


def scored_runs(root: Path) -> dict[str, dict]:
    """{run name: {episode id: scored record}} for every run in runs/ with a ranking or scores: every interview score, and each
    Social score the site lists. The Social list shows an episode whose score is at MIN_SCORE or higher and that has a page,
    which its claims always give it. Its score is the site's choice (site.episode_scores over the scores each run made,
    site.scored_here); an episode with no such score, which the site drops, is held to the scores the runs carry."""
    folders = [d for d in sorted((root / "runs").iterdir()) if d.is_dir()] if (root / "runs").is_dir() else []
    out, social = {}, []
    for d in folders:
        read = {name: json.loads((d / name).read_text(encoding="utf-8")) for name in (*SCORED, SOCIAL_SCORED, "report.json")
                if (d / name).is_file()}
        if not any(name in read for name in (*SCORED, SOCIAL_SCORED)):
            continue
        records = lambda name: [e for e in (read.get(name) or {}).get("episodes") or [] if isinstance(e, dict) and isinstance(e.get("score"), int)]
        out[d.name] = {e["episode_id"]: e for name in SCORED for e in records(name)}
        doc = read.get(SOCIAL_SCORED) or {}
        social.append({"name": d.name, "date": run_date(d.name, read.get("ranked.json"), read.get("report.json")),
                       "rubric": doc.get("rubric") or 1, "carried": records(SOCIAL_SCORED)})
    social.sort(key=lambda r: (r["date"], r["name"]), reverse=True)
    kept = episode_scores([{**r, "scored": [e for e in r["carried"] if scored_here(e, r["name"])]} for r in social])
    with_claims = {e["episode_id"] for r in social for e in r["carried"] if e.get("claims")}
    for r in social:
        out[r["name"]].update({e["episode_id"]: e for e in r["carried"] if e["episode_id"] in with_claims
                               and kept.get(e["episode_id"], (e, 0))[0]["score"] >= MIN_SCORE})
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
