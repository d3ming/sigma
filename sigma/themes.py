"""Weekly themes: `runs/<week>/themes.json`, written by the operator agent (prompts/themes.md), held to the rules below, and
exported to `published/<run>/themes.json` with every cited claim spelled out.

Code only checks and resolves; choosing the themes is the agent's judgment.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema

from . import library, ranked as ranked_mod, report

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "themes.schema.json"
FILE = "themes.json"
DEFAULT_TOP = 15


class ThemesError(ValueError):
    """themes.json is invalid; the message is one `themes: ...` line per problem."""


def norm_ticker(t: str) -> str:
    """Same spelling the library gives a ticker: upper case, except `private:Name`."""
    t = t.strip()
    return t if t.lower().startswith("private:") else t.upper()


def _fold(s: str) -> str:
    return " ".join(str(s).casefold().split())


def _manifest(run_dir: Path) -> dict | None:
    try:
        return {e["episode_id"]: e for e in json.loads((run_dir / "manifest.json").read_text()).get("episodes", [])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def check(themes: dict, ranked: dict, run_dir: str | Path, top: int | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a themes.json against the run's ranked.json and transcripts. `top` is how many ranked
    episodes the digest publishes (None: all of them). Rules, in order:

    - schema/themes.schema.json; `week_of` is a date equal to ranked.json's; `run` is the run folder's name
    - every theme `episode_ids` entry is an episode in ranked.json
    - every evidence item is an episode of that theme, inside the published top N, with an existing claim_index
    - evidence spans at least 2 distinct `source` (show) values
    - every cited claim passes the claim checks `publish` runs (report.ranked_check); one that fails invalidates the theme
    - theme `tickers` are all on the cited claims
    - headline and summaries copy no 12-word run from the transcript of a cited episode
    Without a manifest.json the last two grounding checks are skipped with one warning, as `publish` does for claims."""
    run_dir = Path(run_dir)
    try:
        jsonschema.validate(themes, json.loads(SCHEMA_PATH.read_text()))
    except jsonschema.ValidationError as exc:
        where = "/".join(map(str, exc.absolute_path)) or "root"
        return [f"themes: schema: {where}: {exc.message}"], []
    errors: list[str] = []
    warnings: list[str] = []
    eps = {e["episode_id"]: e for e in ranked["episodes"]}
    limit = top if top else len(ranked["episodes"])
    in_top = {e["episode_id"] for e in ranked["episodes"] if e["rank"] <= limit}

    try:
        date.fromisoformat(themes["week_of"])
    except ValueError:
        errors.append(f"themes: week_of {themes['week_of']!r} is not a date")
    if themes["week_of"] != ranked.get("week_of"):
        errors.append(f"themes: week_of {themes['week_of']} differs from ranked.json week_of {ranked.get('week_of')}")
    if themes["run"] != run_dir.resolve().name:
        errors.append(f"themes: run {themes['run']!r} is not this run folder's name {run_dir.resolve().name!r}")

    man = _manifest(run_dir)
    if man is None:
        warnings.append(f"themes: no readable manifest.json in {run_dir}; cited claims and copied wording not checked against transcripts")
    bad_claims: dict[tuple[str, int | None], str] = {}
    if man is not None:
        cited = {ev["episode_id"] for t in themes["themes"] for ev in t["evidence"] if ev["episode_id"] in eps}
        for eid, idx, msg in report.ranked_check({"episodes": [eps[i] for i in sorted(cited)]}, run_dir)[0]:
            bad_claims.setdefault((eid, idx), msg)

    grams: dict[str, set] = {}

    def transcript_grams(eid: str) -> set:
        if eid not in grams:
            row = (man or {}).get(eid)
            grams[eid] = report._load_transcript(run_dir, row)[1] if row and row.get("has_transcript") else set()
        return grams[eid]

    def copied(text: str, ids: list[str]) -> str | None:
        for eid in ids:
            if run := report._longest_copy(text, transcript_grams(eid)):
                return f"{len(run)} consecutive words copied verbatim from the transcript of {eid}"
        return None

    all_cited: list[str] = []
    for i, t in enumerate(themes["themes"]):
        where = f"themes: themes[{i}] {t['title']!r}"
        for eid in t["episode_ids"]:
            if eid not in eps:
                errors.append(f"{where}: episode_ids: {eid} is not in ranked.json")
        sources, claim_tickers, cited_ids = set(), set(), []
        for j, ev in enumerate(t["evidence"]):
            eid, k = ev["episode_id"], ev["claim_index"]
            at = f"{where}: evidence[{j}] ({eid} claims[{k}])"
            if eid not in eps:
                errors.append(f"{at}: {eid} is not in ranked.json")
                continue
            if eid not in in_top:
                errors.append(f"{at}: episode is rank {eps[eid]['rank']}, outside the published top {limit}")
            if eid not in t["episode_ids"]:
                errors.append(f"{at}: episode is not in this theme's episode_ids")
            cited_ids.append(eid)
            claims = eps[eid]["claims"]
            if k >= len(claims):
                errors.append(f"{at}: claim_index out of range; the episode has {len(claims)} claims")
                continue
            sources.add(_fold(eps[eid]["source"]))
            if msg := bad_claims.get((eid, k)) or bad_claims.get((eid, None)):
                errors.append(f"{at}: the claim fails the publish checks: {msg}")
            claim_tickers.update(norm_ticker(x) for x in claims[k]["ticker"])
        if len(sources) < 2:
            errors.append(f"{where}: evidence comes from {len(sources)} distinct show(s); it needs at least 2")
        extra = [x for x in t["tickers"] if norm_ticker(x) not in claim_tickers]
        if extra:
            errors.append(f"{where}: tickers {extra} are not on any cited claim")
        ids = list(dict.fromkeys(cited_ids + [e for e in t["episode_ids"] if e in eps]))
        all_cited += ids
        if man is not None and (msg := copied(t["summary"], ids)):
            errors.append(f"{where}: summary: {msg}")
    if man is not None and (msg := copied(themes["headline"], list(dict.fromkeys(all_cited)))):
        errors.append(f"themes: headline: {msg}")
    return errors, warnings


def check_run(run_dir: str | Path, ranked: dict | None = None, top: int | None = None) -> tuple[dict | None, list[str], list[str]]:
    """Read <run>/themes.json and check it: (themes or None when unreadable, errors, warnings). `ranked` is the loaded
    ranked.json when the caller has it. Raises FileNotFoundError when the run has no themes.json."""
    run_dir = Path(run_dir)
    try:
        text = (run_dir / FILE).read_text()
    except OSError:
        raise FileNotFoundError(f"no {FILE} in {run_dir}") from None
    try:
        themes = json.loads(text)
    except ValueError as exc:
        return None, [f"themes: {FILE} is not valid JSON: {exc}"], []
    if ranked is None:
        try:
            ranked = ranked_mod.load(run_dir / "ranked.json")
        except (OSError, ValueError) as exc:  # includes RankedError
            return themes, [f"themes: cannot read ranked.json in {run_dir} ({exc})"], []
    return themes, *check(themes, ranked, run_dir, top)


def resolve(themes: dict, ranked: dict, youtube_urls: dict | None = None) -> dict:
    """The published form of a valid themes.json: each evidence item carries its claim text, speaker, show, episode title,
    timestamp and a link to the moment, and each theme says how many of the ranked episodes it came up in."""
    eps = {e["episode_id"]: e for e in ranked["episodes"]}
    total = len(ranked["episodes"])
    out = []
    for t in themes["themes"]:
        ev = []
        for item in t["evidence"]:
            e = eps[item["episode_id"]]
            c = e["claims"][item["claim_index"]]
            link = library.ts_link((youtube_urls or {}).get(e["episode_id"]) or e.get("url") or None, c["timestamp"])
            ev.append({"episode_id": e["episode_id"], "claim_index": item["claim_index"], "claim": c["claim"], "speaker": c["speaker"],
                       "show": e["source"], "episode_title": e["title"], "timestamp": c["timestamp"], "link": link})
        out.append({"title": t["title"], "summary": t["summary"], "stance": t["stance"],
                    "tickers": list(dict.fromkeys(norm_ticker(x) for x in t["tickers"])), "episode_ids": t["episode_ids"],
                    "came_up_in": {"episodes": len(t["episode_ids"]), "of": total}, "evidence": ev})
    return {"week_of": themes["week_of"], "run": themes["run"], "headline": themes["headline"], "themes": out}


def export(run_dir: str | Path, top: int | None = None, youtube_urls: dict | None = None) -> dict | None:
    """The resolved themes for published/<run>/themes.json, or None when the run has no themes.json.
    Raises ThemesError (one line per problem) when the file is invalid, so nothing is written from a bad file."""
    run_dir = Path(run_dir)
    if not (run_dir / FILE).exists():
        return None
    themes, errors, _ = check_run(run_dir, top=top)
    if errors:
        raise ThemesError("\n".join(errors))
    return resolve(themes, ranked_mod.load(run_dir / "ranked.json"), youtube_urls)
