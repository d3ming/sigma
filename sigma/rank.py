"""Scoring plumbing: split a run into reader batches, then merge the readers' outputs into scores.json (a daily run)
or ranked.json (a weekly or custom run).

Episodes from influencer sources (creators who pick stocks; `style: influencer` in sources.yaml) are a different kind of
signal from interviews, so they are scored apart: batches `rank/influencer-N-in.json` read by prompts/rank-influencer.md, merged
into `scores-influencer.json`. They never enter scores.json, ranked.json or the select candidates.

Every episode is scored once, by the first run that transcribes it; the library keeps that score. A later run reuses
it (`scored_in`) instead of reading the episode again, and may re-score a blind sample as an eval that measures drift.
Code does the mechanical parts (condensing, batching, dedupe, ordering, notes); the readers (agents following
prompts/rank.md) do the judgment (scores, claims).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

ANCHOR_SECONDS = 30
RANK_DIR = "rank"
RUBRIC = Path(__file__).resolve().parent.parent / "prompts" / "rank.md"
INFLUENCER_RUBRIC = RUBRIC.with_name("rank-influencer.md")
INFLUENCER_STYLE = "influencer"
INFLUENCER_FILE = "scores-influencer.json"


def is_influencer(row: dict) -> bool:
    """A manifest row from an influencer source. Rows written before `style` existed are interviews."""
    return row.get("style") == INFLUENCER_STYLE


def rubric_version(path: Path = RUBRIC) -> int:
    """The `Rubric version: N` line at the top of prompts/rank.md. Scores are reused only within a version, so bumping
    it is how a rubric change re-scores the library (see skills/score-eval)."""
    m = re.search(r"^Rubric version: (\d+)", path.read_text(), re.M) if path.exists() else None
    return int(m.group(1)) if m else 1


def _seconds(stamp: str) -> int:
    parts = [int(x) for x in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def condense(md: str, step: int = ANCHOR_SECONDS) -> str:
    """Keep the front matter and description; join the transcript into paragraphs that start with a [timestamp] every `step`
    seconds. Cuts reader input roughly in half without losing the timestamps claims must cite."""
    out, buf, last, in_body = [], [], -10**9, False
    for line in md.splitlines():
        m = re.match(r"\[(\d+:\d+(?::\d+)?)\]\s?(.*)", line.strip())
        if not m:
            if not in_body:
                out.append(line)
            continue
        in_body = True
        t = _seconds(m.group(1))
        if t - last >= step:
            if buf:
                out.append(" ".join(buf))
                buf = []
            buf.append(f"[{m.group(1)}]")
            last = t
        buf.append(m.group(2))
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


def _item(run_dir: Path, out: Path, e: dict) -> dict | None:
    if not (run_dir / e["file"]).exists():
        print(f"[rank-prep] skip {e['episode_id']}: {e['file']} is missing")
        return None
    (out / "cond" / e["file"]).write_text(condense((run_dir / e["file"]).read_text()))
    return {"episode_id": e["episode_id"], "file": f"{RANK_DIR}/cond/{e['file']}", "title": e["title"],
            "source": e["source"], "tier": e["tier"], "style": e.get("style") or "interview", "published": e["published"], "url": e["url"],
            "minutes": e.get("transcript_minutes"), "transcript_source": e.get("transcript_source")}


def _deal(todo: list[dict], n: int) -> list[list[dict]]:
    """Deal episodes, largest first, snaking across n batches so each carries similar total text."""
    todo.sort(key=lambda e: (-(e.get("transcript_chars") or 0), e["episode_id"]))
    groups: list[list[dict]] = [[] for _ in range(min(n, len(todo)))]
    for i, e in enumerate(todo):
        k = len(groups)
        groups[i % k if (i // k) % 2 == 0 else k - 1 - i % k].append(e)
    return groups


def _reuse(rows: list[dict], stored: dict) -> list[dict]:
    return [{**{k: e[k] for k in ("episode_id", "title", "url", "source", "tier", "published")},
             **{k: stored[e["episode_id"]][k] for k in ("score", "reason", "claims")},
             "scored_in": stored[e["episode_id"]]["scored_run"]} for e in rows if e["episode_id"] in stored]


def prep(run_dir: Path, batches: int = 4, rescore: bool = False, eval_n: int = 0, db=None, influencer_batches: int = 2) -> dict:
    """Write rank/cond/<episode>.md and rank/batch-N-in.json for transcribed episodes the library has not scored
    (balanced by size), rank/stored.json for the ones it has, and with `eval_n` rank/eval-in.json: a blind sample of
    stored episodes to re-score. `rescore` ignores stored scores and batches everything. Influencer episodes
    go the same way into rank/influencer-N-in.json and rank/influencer-stored.json, checked against the stored scores made under
    the influencer rubric, and are left out of the interview batches, the stored list and the eval sample."""
    from . import library

    man = json.loads((run_dir / "manifest.json").read_text())
    all_rows = [e for e in man["episodes"] if e.get("has_transcript") and not e.get("fallback_text")]
    rows = [e for e in all_rows if not is_influencer(e)]
    irows = [e for e in all_rows if is_influencer(e)]
    out = run_dir / RANK_DIR
    (out / "cond").mkdir(parents=True, exist_ok=True)
    stored = {} if rescore else library.stored_scores([e["episode_id"] for e in rows], db, rubric=rubric_version())
    reuse = _reuse(rows, stored)
    (out / "stored.json").write_text(json.dumps(reuse, indent=1, ensure_ascii=False) + "\n")
    todo = [e for e in rows if e["episode_id"] not in stored]
    groups = _deal(todo, batches)
    for k, group in enumerate(groups, 1):
        items = [it for e in group if (it := _item(run_dir, out, e))]
        (out / f"batch-{k}-in.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
    istored = {} if rescore else library.stored_scores([e["episode_id"] for e in irows], db,
                                                       rubric=rubric_version(INFLUENCER_RUBRIC), style="influencer")
    ireuse = _reuse(irows, istored)
    itodo = [e for e in irows if e["episode_id"] not in istored]
    igroups = _deal(itodo, influencer_batches)
    if irows:
        (out / "influencer-stored.json").write_text(json.dumps(ireuse, indent=1, ensure_ascii=False) + "\n")
    for k, group in enumerate(igroups, 1):
        items = [it for e in group if (it := _item(run_dir, out, e))]
        (out / f"influencer-{k}-in.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
    sample = []
    if eval_n and reuse:
        by_id = {e["episode_id"]: e for e in rows}
        picks = random.Random(run_dir.name).sample(reuse, min(eval_n, len(reuse)))
        sample = [it for r in picks if (it := _item(run_dir, out, by_id[r["episode_id"]]))]
        (out / "eval-in.json").write_text(json.dumps(sample, indent=1, ensure_ascii=False) + "\n")
    return {"transcribed": len(rows), "without_transcript": len(man["episodes"]) - len(all_rows), "batches": len(groups),
            "to_score": len(todo), "stored": len(reuse), "eval": len(sample),
            "influencer": len(irows), "influencer_batches": len(igroups), "influencer_to_score": len(itodo), "influencer_stored": len(ireuse)}


def _fingerprint(run_dir: Path, row: dict) -> str | None:
    """Same transcript on two feeds -> same fingerprint. Samples three slices (25/50/75%) so a shared pre-roll or intro
    at the start does not make two different episodes look alike."""
    md = run_dir / row["file"]
    if not md.exists():
        return None
    body = md.read_text().partition("## Transcript")[2]
    text = re.sub(r"\W+", " ", re.sub(r"\[[\d:]+\]\s*", "", body).lower()).strip()
    if len(text) < 2000:
        return None
    n = len(text)
    return hashlib.sha1("|".join(text[int(n * f):int(n * f) + 300] for f in (0.25, 0.5, 0.75)).encode()).hexdigest()


def apply_tier3(ranked: list[dict]) -> tuple[list[dict], list[str]]:
    """prompts/rank.md: at most 2 tier-3 episodes, and none in ranks 1-3. The rule spans batches, so the merge enforces it."""
    t3 = [r for r in ranked if r["tier"] == 3]
    keep = {r["episode_id"] for r in t3[:2]}
    cut = [r["title"] for r in t3[2:]]
    rest = [r for r in ranked if r["tier"] != 3 or r["episode_id"] in keep]
    top = [r for r in rest if r["tier"] != 3][:3]
    moved = [r["title"] for r in rest[:3] if r["tier"] == 3]
    head_ids = {r["episode_id"] for r in top}
    out = top + [r for r in rest if r["episode_id"] not in head_ids]
    return out, cut + moved


def merge(run_dir: Path, ranked_by: str, week_of: str | None = None, ranking: bool = True, influencer: bool = False) -> dict:
    """Merge rank/batch-*-out.json and rank/stored.json into ranked.json data. Same transcript on two feeds keeps the
    higher-scored row (then better tier); order is score, tier, newest first (prompts/rank.md). `ranking=False` (a
    daily's scores.json) keeps every scored episode, so the tier-3 cap is not applied. `influencer=True` merges the influencer
    batches (influencer-*-out.json, influencer-stored.json) for scores-influencer.json and accepts only influencer
    episodes; the interview merge refuses them, so neither list can carry the other's episodes."""
    man = json.loads((run_dir / "manifest.json").read_text())
    by_id = {e["episode_id"]: e for e in man["episodes"]}
    rows, dropped, unknown = [], [], []
    files = sorted((run_dir / RANK_DIR).glob("influencer-*-out.json" if influencer else "batch-*-out.json"))
    stored_p = run_dir / RANK_DIR / ("influencer-stored.json" if influencer else "stored.json")
    if stored_p.exists():
        files.append(stored_p)
    for f in files:
        for r in json.loads(f.read_text()):
            (rows if r["episode_id"] in by_id else unknown).append(r)
    if unknown:
        raise ValueError("readers returned ids not in the manifest: " + ", ".join(r["episode_id"] for r in unknown[:5]))
    wrong = [r["episode_id"] for r in rows if is_influencer(by_id[r["episode_id"]]) != influencer]
    if wrong:
        raise ValueError(f"{', '.join(wrong[:5])}: " + (
            "not an influencer episode; it is scored in a batch-N file under prompts/rank.md" if influencer else
            "an influencer episode; it is scored in an influencer-N file under prompts/rank-influencer.md"))
    seen_ids, rows2 = set(), []
    for r in rows:
        if r["episode_id"] not in seen_ids:
            seen_ids.add(r["episode_id"])
            rows2.append(r)
    best: dict[str, dict] = {}
    for r in sorted(rows2, key=lambda r: (-r["score"], r["tier"], r["episode_id"])):
        fp = _fingerprint(run_dir, by_id[r["episode_id"]]) or r["episode_id"]
        if fp in best:
            dropped.append(r["title"])
        else:
            best[fp] = r
    ranked = sorted(best.values(), key=lambda r: (-r["score"], r["tier"], "".join(chr(255 - ord(c)) for c in r["published"][:10]),
                                                  r["episode_id"]))
    ranked, cut = apply_tier3(ranked) if ranking and not influencer else (ranked, [])
    eps = [{**{k: r[k] for k in ("episode_id", "title", "url", "source", "tier", "published", "score", "reason", "claims")},
            **({"scored_in": r["scored_in"]} if r.get("scored_in") else {}), "rank": i} for i, r in enumerate(ranked, 1)]
    with_text = by_id_with_text(man)
    apart = sum(is_influencer(e) for e in with_text)
    untranscribed = len(man["episodes"]) - len(with_text)
    notes = (f"{len(man['episodes'])} episodes fetched; {len(eps)} with transcripts are ranked and {untranscribed} had no usable "
             f"transcript and are not ranked, so audio-only shows are underrepresented."
             + (f" {apart} influencer episodes are scored apart." if apart and not influencer else "")
             + (f" {sum(1 for e in eps if e.get('scored_in'))} keep the score they were given when first scored."
                if any(e.get("scored_in") for e in eps) else "")
             + (f" Same-transcript duplicates merged: {'; '.join(t[:60] for t in dropped)}." if dropped else "")
             + (f" Tier-3 cap (2, never top 3) removed or moved: {'; '.join(t[:60] for t in cut)}." if cut else ""))
    # an influencer's older video must not move the interview list's date, nor the reverse
    kind = [e for e in man["episodes"] if is_influencer(e) == influencer] or man["episodes"]
    return {"week_of": week_of or min(e["published"][:10] for e in kind), "run_dir": f"runs/{run_dir.name}",
            "ranked_by": ranked_by, "rubric": rubric_version(INFLUENCER_RUBRIC if influencer else RUBRIC), "notes": notes, "episodes": eps}


def by_id_with_text(man: dict) -> list[dict]:
    return [e for e in man["episodes"] if e.get("has_transcript") and not e.get("fallback_text")]
