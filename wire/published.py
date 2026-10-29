"""Copy a run's published outputs into published/<run>/, which is committed so cloud agents can read past reports.

Only our own writing and public metadata go there: the agent's JSON outputs, the rendered markdown, a slim episode
list and a claims.jsonl. Transcripts, show descriptions and anything from the reference newsletter stay in runs/.

What a published/<run>/ folder holds, for the programs and agents that read it (the site, `wire stance-prep`, cloud agents):
  FILES and digest-*.md   the run's outputs as the agent wrote them, in the schemas under schema/; one over MAX_BYTES is skipped
  episodes.json           one row per episode with EPISODE_KEYS (metadata only; `style` is "influencer" for creators who pick
                          stocks) and the listen links LINK_KEYS found at export
  claims.jsonl            one claim per line, the shape of `library export` (schema/library-claim.schema.json) with `run` and
                          without `transcript_path`
  themes.json             a weekly with themes only: the resolved form (themes.resolve)
  stances.jsonl           stance labels, added later by `stance-merge` (stance.py); a re-export keeps the file
X editions and their stance labels live apart, in published/x/editions/<date>.json (xdaily.public_edition) and
published/x/stances/<date>.jsonl.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "published"
FILES = ("selected.json", "report.json", "report.md", "ranked.json", "scores.json", "scores-influencer.json")
STANCES = "stances.jsonl"
MAX_BYTES = 1_000_000  # a published file this large is almost certainly not a report; keep it out of git
EPISODE_KEYS = ("episode_id", "title", "source", "tier", "style", "published", "url", "youtube_id", "transcript_url",
                "has_transcript", "transcript_source", "excluded")


LINK_KEYS = ("youtube_url", "apple_url", "spotify_url", "spotify_kind")
CONFIG = Path(__file__).resolve().parent.parent


def episodes(manifest: dict, found: dict | None = None) -> list[dict]:
    """Episode metadata without descriptions or local paths. `found` ({episode_id: links}) adds the listen links; a
    youtube_url is also derived from youtube_id."""
    out = []
    for e in manifest.get("episodes", []):
        row = {k: e[k] for k in EPISODE_KEYS if e.get(k) not in (None, "")}
        links = dict((found or {}).get(e.get("episode_id"), {}))
        if e.get("youtube_id") and not links.get("youtube_url"):
            links["youtube_url"] = f"https://www.youtube.com/watch?v={e['youtube_id']}"
        row.update({k: links[k] for k in LINK_KEYS if links.get(k)})
        out.append(row)
    return out


def listed_ids(run_dir: Path) -> list[str]:
    """Episodes the published files show, the only ones worth looking links up for: those in ranked.json, report.json,
    selected.json or scores-influencer.json (Social lists every episode with its YouTube link, so a creator's podcast-feed copy
    needs the lookup too), and those in scores.json that have claims (a daily's claims come from it)."""
    ids: list[str] = []
    for name, needs_claims in (("ranked.json", False), ("report.json", False), ("selected.json", False),
                               ("scores-influencer.json", False), ("scores.json", True)):
        try:
            data = json.loads((run_dir / name).read_text())
        except (OSError, ValueError):
            continue
        ids += [e["episode_id"] for e in data.get("episodes", [])
                if isinstance(e, dict) and e.get("episode_id") and (e.get("claims") or not needs_claims)]
    return list(dict.fromkeys(ids))


def has_episode_link(links: dict) -> bool:
    """A link to the episode itself: YouTube, Apple, or a Spotify episode page (a Spotify show page is not one)."""
    return bool(links.get("youtube_url") or links.get("apple_url") or (links.get("spotify_url") and links.get("spotify_kind") != "show"))


def default_resolver(rows: list[dict]) -> dict:
    """Network lookup (YouTube through yt-dlp, Apple through iTunes, Spotify's public pages). Best effort."""
    from . import links, showlinks

    return links.listen_links(rows, showlinks.by_name(CONFIG / "show_links.yaml"), links.sources_by_name(CONFIG / "sources.yaml"))


def resolve_links(run_dir: Path, manifest: dict, previous: list[dict], resolver=None) -> dict:
    """{episode_id: {youtube_url, apple_url, spotify_url, spotify_kind}} for the episodes the run publishes (listed_ids). Anything
    an earlier export already had is kept when the lookup finds nothing, so a network failure never loses a link, and an episode
    that already has a YouTube and an Apple link is not looked up again. Episodes still without a link of their own are printed
    as a warning, never an error. `resolver` is a function(rows) -> dict; None means the real lookup unless PA_NO_LINK_LOOKUP is
    set; False skips it."""
    found = {e["episode_id"]: {k: e[k] for k in LINK_KEYS if e.get(k)} for e in previous if e.get("episode_id")}
    if resolver is False or (resolver is None and os.environ.get("PA_NO_LINK_LOOKUP")):
        return found
    ids = set(listed_ids(run_dir))
    rows = [{**e, "show": e.get("source")} for e in manifest.get("episodes", []) if e.get("episode_id") in ids]
    todo = [r for r in rows if not (found.get(r["episode_id"], {}).get("youtube_url") and found[r["episode_id"]].get("apple_url"))]
    try:
        new = (resolver or default_resolver)(todo)
    except Exception as exc:
        print(f"[published] warning: listen links not looked up ({type(exc).__name__}: {exc})")
        new = {}
    for eid, links in new.items():
        found.setdefault(eid, {}).update({k: v for k, v in links.items() if k in LINK_KEYS and v})
    bare = [r for r in rows if not has_episode_link({**found.get(r["episode_id"], {}), **({"youtube_url": "y"} if r.get("youtube_id") else {})})]
    if bare:
        print(f"[published] warning: {len(bare)} of {len(rows)} episodes have no Apple, Spotify or YouTube link: "
              + "; ".join(f"{r.get('source')}: {(r.get('title') or '')[:50]}" for r in bare))
    return found


def relink(run_dir: str | Path, root: str | Path | None = None, name: str | None = None, resolver=None) -> dict:
    """Look the links up again for a run that is already in published/<name>/ and write only them, into episodes.json and the
    youtube_url/link of claims.jsonl. Nothing else in the folder changes. The run folder supplies what a lookup needs (guid,
    audio url, length, show notes). Returns {"episodes": n listed, "before": n without a link, "after": n without a link}."""
    run_dir = Path(run_dir).resolve()
    dest = Path(root or ROOT) / (name or run_dir.name)
    try:
        previous = json.loads((dest / "episodes.json").read_text())
        manifest = json.loads((run_dir / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(f"need {dest / 'episodes.json'} and {run_dir / 'manifest.json'} ({exc})") from exc
    ids = listed_ids(run_dir)
    own = lambda rows: sum(1 for e in rows if e.get("episode_id") in ids and not has_episode_link(
        {**e, **({"youtube_url": "y"} if e.get("youtube_id") else {})}))
    before = own(previous)
    found = resolve_links(run_dir, manifest, previous, resolver)
    for row in previous:
        links = dict(found.get(row.get("episode_id"), {}))
        if row.get("youtube_id") and not links.get("youtube_url"):
            links["youtube_url"] = f"https://www.youtube.com/watch?v={row['youtube_id']}"
        row.update({k: links[k] for k in LINK_KEYS if links.get(k)})
    (dest / "episodes.json").write_text(json.dumps(previous, indent=1, ensure_ascii=False) + "\n")
    claims_p = dest / "claims.jsonl"
    if claims_p.is_file():
        from . import library

        rows = [json.loads(line) for line in claims_p.read_text().split("\n") if line.strip()]
        for row in rows:
            yt = found.get(row.get("episode_id"), {}).get("youtube_url")
            if yt and not row.get("youtube_url"):
                row["youtube_url"], row["link"] = yt, library.ts_link(yt, row.get("timestamp"))
        claims_p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return {"episodes": len(ids), "before": before, "after": own(previous)}


def _read_claims(f: Path) -> list[dict]:
    return [json.loads(line) for line in f.read_text().split("\n") if line.strip()]


def restated_problems(rows: list[dict], where: str) -> list[str]:
    """One line per pair of claims in `rows` that make the same point (claimdedupe.restated_pairs): where, episode, both timestamps
    and texts. Empty when the claims are clean."""
    from . import claimdedupe

    def at(c):
        t = c.get("timestamp")
        return f"{int(t) // 60}:{int(t) % 60:02d}" if isinstance(t, int | float) else "?"

    return [f"{where}: {str(a.get('title') or a.get('episode_id'))[:60]}: {a.get('speaker')} @{at(a)} \"{(a.get('text') or '')[:70]}\" "
            f"restates @{at(b)} \"{(b.get('text') or '')[:70]}\"" for a, b in claimdedupe.restated_pairs(rows)]


def check_claims(root: str | Path | None = None) -> list[str]:
    """The data-quality check: the problems (restated_problems) in every published/<name>/claims.jsonl. Nothing is changed."""
    root = Path(root or ROOT)
    return [m for d in sorted(p for p in root.iterdir() if (p / "claims.jsonl").is_file())
            for m in restated_problems(_read_claims(d / "claims.jsonl"), f"published/{d.name}")]


def dedupe_claims(root: str | Path | None = None, names: list[str] | None = None, write: bool = True) -> dict:
    """Collapse the restated claims (claimdedupe) in the claims.jsonl of published/<name>/ for each name (all when None), in
    place and nothing else. Re-running changes nothing. Returns {name: {"before": n, "after": n, "episodes": {episode_id:
    {"title", "removed"}}}} for the folders that have a claims.jsonl."""
    from . import claimdedupe

    root = Path(root or ROOT)
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and (names is None or p.name in names)):
        f = d / "claims.jsonl"
        if not f.is_file():
            continue
        rows = _read_claims(f)
        for r in rows:  # the published shape names the tags `tickers`, which claimdedupe unions
            r.setdefault("tickers", [])
        kept, merged = claimdedupe.dedupe(rows)
        per: dict = {}
        for keep, dropped in merged:
            e = per.setdefault(keep["episode_id"], {"title": keep.get("title"), "removed": 0})
            e["removed"] += len(dropped)
        if write and len(kept) != len(rows):
            f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept))
        out[d.name] = {"before": len(rows), "after": len(kept), "episodes": per}
    return out


def export(run_dir: str | Path, root: str | Path | None = None, name: str | None = None, resolver=None,
           top: int | None = None) -> tuple[Path, list[str]]:
    """Write published/<name>/ from the run folder (replacing what was there). Returns the folder and the files written.
    episodes.json and claims.jsonl also carry per-episode listen links (see resolve_links for `resolver`).
    A run with a themes.json also gets the resolved themes.json (themes.py); `top` is the digest's top N that its
    evidence must sit in. An invalid themes.json raises ThemesError before anything is replaced."""
    from . import library, themes

    run_dir = Path(run_dir).resolve()
    dest = Path(root or ROOT) / (name or run_dir.name)
    srcs = [run_dir / f for f in FILES] + sorted(run_dir.glob("digest-*.md"))
    srcs = [p for p in srcs if p.is_file()]
    if not srcs:
        raise FileNotFoundError(f"nothing published in {run_dir} yet (no report.json, ranked.json or digest)")
    man = run_dir / "manifest.json"
    manifest = json.loads(man.read_text()) if man.exists() else {}
    try:
        previous = json.loads((dest / "episodes.json").read_text())
    except (OSError, ValueError):
        previous = []
    from .ranked import private_hits

    for p in srcs:  # before anything is replaced: a private phrase in any file stops the export
        if p.suffix in (".md", ".json", ".jsonl") and (hits := private_hits(p.read_text(encoding="utf-8", errors="replace"))):
            raise ValueError(f"[published] {p.name} looks private ({hits}); fix it in the run folder, never in published/")
    found = resolve_links(run_dir, manifest, previous, resolver)
    youtube = {e["episode_id"]: u for e in episodes(manifest, found) if (u := e.get("youtube_url"))}
    resolved_themes = themes.export(run_dir, top=top, youtube_urls=youtube)
    # the claims are made, and checked, before the folder is replaced: a refusal leaves the previous export as it was
    with tempfile.TemporaryDirectory() as d:  # same claim shape as `library export` (schema/library-claim.schema.json)
        db = Path(d) / "lib.sqlite"
        library.ingest_run(run_dir, db=db, transcripts=False)
        rows = []
        for row in library.query_claims(db, limit=0):
            row.pop("transcript_path", None)  # a local path means nothing to a cloud agent
            row["run"] = dest.name
            yt = found.get(row.get("episode_id"), {}).get("youtube_url")
            if yt and not row.get("youtube_url"):  # a video found at export time: claim links open it at the moment
                row["youtube_url"], row["link"] = yt, library.ts_link(yt, row.get("timestamp"))
            rows.append(row)
    if problems := restated_problems(rows, f"published/{dest.name}"):  # the publish gate: ingest merges these, so this means a bug
        raise ValueError("[published] the same point is listed twice:\n" + "\n".join(problems[:10]))
    stances = dest / STANCES  # labels (stance.py) are made after the export and outlive it: a re-export keeps them
    kept = stances.read_bytes() if stances.is_file() else None
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if kept is not None:
        stances.write_bytes(kept)
    written, skipped = [], []
    for p in srcs:
        if p.stat().st_size > MAX_BYTES:
            skipped.append(p.name)
            continue
        shutil.copy2(p, dest / p.name)
        written.append(p.name)
    if man.exists():
        (dest / "episodes.json").write_text(json.dumps(episodes(manifest, found), indent=1, ensure_ascii=False) + "\n")
        written.append("episodes.json")
    (dest / "claims.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    written.append("claims.jsonl")
    if resolved_themes:
        (dest / themes.FILE).write_text(json.dumps(resolved_themes, indent=1, ensure_ascii=False) + "\n")
        written.append(themes.FILE)
    for s in skipped:
        print(f"[published] skipped {s}: over {MAX_BYTES // 1000} KB")
    return dest, written
