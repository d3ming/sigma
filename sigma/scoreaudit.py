"""`sigma score-audit`: every stored score whose transcript cannot be shown to be what it was scored on (theta#93).
Report only: it changes no score, ranking or file."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .transcripts import (LOW_COVERAGE, check, choose, copy_of, fuller, media_seconds, minutes, partial, record, same_media,
                          unverified_length)

SCORE_FILES = ("ranked.json", "scores.json", "scores-influencer.json")
LOW = "unverified length"


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def audit(root: Path) -> dict:
    runs, pub = root / "runs", root / "published"
    published = {p.name for p in pub.iterdir()} if pub.is_dir() else set()
    rows, here, copies = {}, {}, defaultdict(list)
    for mp in sorted(runs.glob("*/manifest.json")):
        for r in (_read(mp) or {}).get("episodes", []):
            rows[(mp.parent.name, r["episode_id"])] = r
            if c := copy_of(mp.parent, r):
                here[(mp.parent.name, r["episode_id"])] = c
                copies[r["episode_id"]].append(c)
    total, legacy, flagged = 0, 0, []
    for run_dir in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        for name in SCORE_FILES:
            for e in (_read(run_dir / name) or {}).get("episodes", []):
                if e.get("score") is None:
                    continue
                total += 1
                eid, rec = e["episode_id"], e.get("transcript")
                legacy += not rec
                why = reasons(rows.get((run_dir.name, eid), {}), here.get((run_dir.name, eid)), copies[eid], rec)
                if why:
                    flagged.append({"run": run_dir.name, "episode_id": eid, "score": e["score"],
                                    "published": run_dir.name in published, "file": name, "reasons": why,
                                    "low_priority": all(r.startswith(LOW) for r in why)})
    flagged.sort(key=lambda f: (f["low_priority"], -f["score"], f["episode_id"], f["run"]))
    return {"scores": total, "flagged": flagged, "episodes": len({f["episode_id"] for f in flagged}),
            "unverifiable_legacy": legacy}


def reasons(row: dict, c, copies: list, rec: dict | None) -> list[str]:
    if c is None:
        return ["no transcript on disk for the scoring run"]
    out = []
    media = media_seconds(row) or max((media_seconds(x.row) or 0 for x in copies), default=0) or None
    if media is None:
        out.append("media length unknown")
    if cut := partial(row):
        out.append(cut)
    if unsure := unverified_length(row):
        out.append(unsure)
    if media and c.end / media < LOW_COVERAGE:
        out.append(f"coverage {c.end / media:.0%}")
    best, _ = choose(copies, row)
    if best and best is not c and same_media(row, best.row) and fuller(best.end, c.end):
        out.append(f"fuller copy of the same media in {best.run} ({minutes(best.end)} vs {minutes(c.end)} min)")
    if rec and check(rec, record(c.path, row)) == "mismatch":
        out.append(f"record mismatch (scored on {minutes(rec['end_seconds'])} min, now {minutes(c.end)} min)")
    return out


def summary(report: dict) -> str:
    review = [f for f in report["flagged"] if not f["low_priority"]]
    return (f"score audit: {len(review)} of {report['scores']} stored scores flagged ({len({f['episode_id'] for f in review})} "
            f"episodes; {sum(f['published'] for f in review)} in published runs), {len(report['flagged']) - len(review)} more of "
            f"unverified length only; {report['unverifiable_legacy']} have no transcript record (unverifiable legacy); "
            "`sigma score-audit` lists them")


def render(report: dict) -> str:
    lines = [summary(report)]
    lines += [f"{f['score']:>2} {'pub' if f['published'] else '   '} {f['episode_id']:<28} {f['run']:<34} {'; '.join(f['reasons'])}"
              for f in report["flagged"]]
    return "\n".join(lines)
