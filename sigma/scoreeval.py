"""Score eval: measure the scoring rubric (prompts/rank.md) against a gold set, so changes to it can be hill-climbed.

The gold set is the owner's judgment written down: a score per episode, a strict order over the top episodes, and
"A beats B" pairs. It lives in data/score-eval/ (git-ignored) with every round's inputs, reader outputs and grades.
Readers never see gold: `prep` writes blind batches like rank-prep's, the operator runs one reader agent per batch,
and `grade` compares. The top of the ranking is what readers see first, so the headline metric is ordering accuracy
among the gold top 15; overall error is a guardrail. See .claude/skills/score-eval/SKILL.md for the loop.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import statistics
from itertools import combinations
from pathlib import Path

from .rank import condense

TOP = 15  # gold top region: ordered strictly, graded pair by pair
PRECISION_AT = 10


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().split("\n") if x.strip()] if path.exists() else []


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _safe(eid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", eid)


def load(flow: Path) -> tuple[list[dict], list[dict]]:
    """Gold rows and owner pairs. A gold row: episode_id, title, show, tier, published, transcript (path), gold (1-10),
    order (1..TOP for the top region, else absent), why, by, split (train or test)."""
    gold = _jsonl(flow / "gold.jsonl")
    if not gold:
        raise SystemExit(f"[score-eval] no gold set at {flow / 'gold.jsonl'}; see .claude/skills/score-eval/SKILL.md")
    orders = sorted(g["order"] for g in gold if g.get("order"))
    if orders != list(range(1, len(orders) + 1)):
        raise SystemExit(f"[score-eval] gold `order` must run 1..N without gaps; found {orders}")
    ids = {g["episode_id"] for g in gold}
    pairs = [p for p in _jsonl(flow / "pairs.jsonl") if p["better"] in ids and p["worse"] in ids]
    return gold, pairs


def pool(db: str | Path | None = None) -> list[dict]:
    """Library episodes with a stored score and a transcript on disk: the candidates a gold set is drawn from."""
    from . import library

    con = library.connect(db)
    rows = con.execute("SELECT episode_id, title, show, tier, published, transcript_path, score, reason FROM episodes "
                       "WHERE score IS NOT NULL AND transcript_path IS NOT NULL ORDER BY score DESC, published DESC")
    out = [{"episode_id": r["episode_id"], "title": r["title"], "show": r["show"], "tier": r["tier"],
            "published": r["published"], "transcript": r["transcript_path"], "score": r["score"], "reason": r["reason"]}
           for r in rows if Path(r["transcript_path"]).exists()]
    con.close()
    return out


def prep(flow: Path, variant: str, rubric: Path, reps: int = 2, size: int = 6) -> dict:
    """Snapshot the rubric into <variant>/ and write <variant>/in/rep<r>-b<k>-in.json: every gold episode once per rep,
    in batches of `size`. Batches are drawn with a seed per rep, not per variant, so every variant scores the same
    batches and a difference between variants is the rubric's, not the company an episode kept."""
    gold, _ = load(flow)
    vdir, cond = flow / variant, flow / "cond"
    (vdir / "in").mkdir(parents=True, exist_ok=True)
    (vdir / "out").mkdir(exist_ok=True)
    cond.mkdir(exist_ok=True)
    shutil.copyfile(rubric, vdir / "rubric.md")
    for g in gold:
        dest = cond / f"{_safe(g['episode_id'])}.md"
        if not dest.exists():
            dest.write_text(condense(Path(g["transcript"]).read_text()))
    batches = 0
    for r in range(reps):
        order = sorted(gold, key=lambda g: g["episode_id"])
        random.Random(f"rep{r}").shuffle(order)
        for k in range(0, len(order), size):
            items = [{"episode_id": g["episode_id"], "file": str((cond / f"{_safe(g['episode_id'])}.md").resolve()),
                      "title": g["title"], "source": g["show"], "tier": g["tier"], "published": g["published"]}
                     for g in order[k:k + size]]
            (vdir / "in" / f"rep{r}-b{k // size + 1}-in.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
            batches += 1
    return {"variant": variant, "episodes": len(gold), "reps": reps, "batches": batches}


def _tau(pairs: list[tuple[float, float]]) -> float:
    """Share of pairs a ranking puts the right way round; a tie counts half."""
    if not pairs:
        return float("nan")
    return sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs) / len(pairs)


def metrics(gold: list[dict], pairs: list[dict], mean: dict[str, float], spread: dict[str, float]) -> dict:
    """Ranking metrics over the gold rows given (a split, or all). `mean` is each episode's mean reader score."""
    g = {x["episode_id"]: x for x in gold if x["episode_id"] in mean}
    top = sorted((x for x in g.values() if x.get("order")), key=lambda x: x["order"])
    # top pairs: every pair inside the gold top region, the better one by gold order
    top_pairs = [(mean[a["episode_id"]], mean[b["episode_id"]]) for a, b in combinations(top, 2)]
    # band pairs: the top pairs whose gold scores differ, the ones a whole-number score can get right
    band_pairs = [(mean[a["episode_id"]], mean[b["episode_id"]]) for a, b in combinations(top, 2) if a["gold"] > b["gold"]]
    # the top region must also beat everything below it
    below = [x for x in g.values() if not x.get("order")]
    edge = [(mean[a["episode_id"]], mean[b["episode_id"]]) for a in top for b in below]
    owner = [(mean[p["better"]], mean[p["worse"]]) for p in pairs if p["better"] in g and p["worse"] in g]
    gold_top = {x["episode_id"] for x in top[:PRECISION_AT]}
    tiers = {x["episode_id"]: x["tier"] for x in g.values()}
    ranked = sorted(g, key=lambda e: (-mean[e], tiers[e], e))[:PRECISION_AT]
    err = [abs(mean[e] - g[e]["gold"]) for e in g]
    return {"n": len(g), "top_pairs": _tau(top_pairs), "band_pairs": _tau(band_pairs), "edge": _tau(edge), "owner_pairs": _tau(owner),
            "p_at_10": len(gold_top & set(ranked)) / max(1, min(PRECISION_AT, len(gold_top))),
            "mae": statistics.fmean(err) if err else float("nan"),
            "within_1": sum(e <= 1 for e in err) / len(err) if err else float("nan"),
            "rep_sd": statistics.fmean(spread[e] for e in g) if g else float("nan")}


def grade(flow: Path, variant: str) -> dict:
    """Read <variant>/out/*-out.json, write results.jsonl (one row per episode per rep) and summary.json (metrics for
    train, test and all). Missing or unknown ids are reported, never silently scored."""
    gold, pairs = load(flow)
    by_id = {g["episode_id"]: g for g in gold}
    vdir = flow / variant
    rows, problems = [], []
    for out in sorted((vdir / "out").glob("rep*-b*-out.json")):
        rep = int(out.name[3:out.name.index("-")])
        sent = {x["episode_id"] for x in json.loads((vdir / "in" / out.name.replace("-out", "-in")).read_text())}
        got = json.loads(out.read_text())
        for r in got:
            if r.get("episode_id") not in sent:
                problems.append(f"{out.name}: unknown id {r.get('episode_id')}")
                continue
            g = by_id[r["episode_id"]]
            s = r.get("score")
            if not isinstance(s, (int, float)):
                problems.append(f"{out.name}: {r['episode_id']} has no numeric score")
                continue
            rows.append({"prompt_id": g["episode_id"], "rep": rep, "prompt": g["title"],
                         "tags": [g["split"], f"gold-{g['gold']}"], "score": s, "gold": g["gold"],
                         "grade": {"abs_err": abs(s - g["gold"]), "within_1": int(abs(s - g["gold"]) <= 1)},
                         "explanation": {"score": r.get("reason", "")}, "adjust": r.get("adjust"),
                         "band": r.get("band")})
        problems += [f"{out.name}: missing {e}" for e in sorted(sent - {r.get('episode_id') for r in got})]
    missing_in = [p.name for p in sorted((vdir / "in").glob("*-in.json"))
                  if not (vdir / "out" / p.name.replace("-in", "-out")).exists()]
    problems += [f"no output for {m}" for m in missing_in]
    _write_jsonl(vdir / "results.jsonl", rows)
    scores: dict[str, list[float]] = {}
    for r in rows:
        scores.setdefault(r["prompt_id"], []).append(r["score"])
    mean = {e: statistics.fmean(v) for e, v in scores.items()}
    spread = {e: statistics.pstdev(v) if len(v) > 1 else 0.0 for e, v in scores.items()}
    summary = {"variant": variant, "problems": problems, "complete": not problems,
               **{split: metrics([g for g in gold if split == "all" or g["split"] == split], pairs, mean, spread)
                  for split in ("all", "train", "test")}}
    prior = vdir / "summary.json"
    keep = {k: v for k, v in (json.loads(prior.read_text()).items() if prior.exists() else []) if k in ("description", "suspicious")}
    (vdir / "summary.json").write_text(json.dumps({**keep, **summary}, indent=1) + "\n")
    return summary


COLUMNS = (("band_pairs", "all"), ("band_pairs", "test"), ("top_pairs", "all"), ("edge", "all"), ("owner_pairs", "all"),
           ("p_at_10", "all"), ("mae", "all"), ("within_1", "all"), ("rep_sd", "all"))


def table(flow: Path) -> str:
    """Markdown status table over every graded variant, baseline first."""
    head = "| variant | change | " + " | ".join(f"{m} ({s})" for m, s in COLUMNS) + " |"
    lines = [head, "|" + "---|" * (len(COLUMNS) + 2)]
    vs = sorted((p for p in flow.iterdir() if (p / "summary.json").exists()),
                key=lambda p: (p.name != "baseline", int(re.sub(r"\D", "", p.name) or 0)))
    for v in vs:
        s = json.loads((v / "summary.json").read_text())
        vals = [s[split].get(m, float("nan")) for m, split in COLUMNS]  # nan: not computed (an older grade)
        cells = ["—" if x != x else f"{x:.2f}" for x in vals]
        flag = "" if s.get("complete") else " (incomplete)"
        lines.append(f"| {v.name}{flag} | {s.get('description', '')} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
