"""Copy a run's outputs into data/published/<run>/ for the site and local tools.

Only our own writing and public metadata go there: the agent's JSON outputs, the rendered markdown, a slim episode
list and a claims.jsonl. Transcripts and show descriptions stay in the run folders.

What a published/<run>/ folder holds, for the programs and agents that read it (the site and `sigma stance-prep`):
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
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .paths import data_root

ROOT = data_root() / "published"
FILES = ("selected.json", "report.json", "report.md", "ranked.json", "scores.json", "scores-influencer.json", "editor.json")
STANCES = "stances.jsonl"
MAX_BYTES = 1_000_000  # a published file this large is almost certainly not a report; keep it out of git
EPISODE_KEYS = ("episode_id", "title", "source", "tier", "style", "published", "url", "youtube_id", "transcript_url",
                "has_transcript", "transcript_source", "excluded", "image_url", "show_image_url")


LINK_KEYS = ("youtube_url", "apple_url", "spotify_url", "spotify_kind")
DATA = data_root()


def episodes(manifest: dict, found: dict | None = None, edits: dict | None = None) -> list[dict]:
    """Episode metadata without descriptions or local paths. `found` ({episode_id: links}) adds the listen links; a
    youtube_url is also derived from youtube_id."""
    out = []
    for e in manifest.get("episodes", []):
        row = {k: e[k] for k in EPISODE_KEYS if e.get(k) not in (None, "")}
        links = dict((found or {}).get(e.get("episode_id"), {}))
        if e.get("youtube_id") and not links.get("youtube_url"):
            links["youtube_url"] = f"https://www.youtube.com/watch?v={e['youtube_id']}"
        row.update({k: links[k] for k in LINK_KEYS if links.get(k)})
        row.update((edits or {}).get(e.get("episode_id"), {}))
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

    return links.listen_links(rows, showlinks.by_name(DATA / "show_links.yaml"), links.sources_by_name(DATA / "sources.yaml"))


def resolve_links(run_dir: Path, manifest: dict, previous: list[dict], resolver=None) -> dict:
    """{episode_id: {youtube_url, apple_url, spotify_url, spotify_kind}} for the episodes the run publishes (listed_ids). Anything
    an earlier export already had is kept when the lookup finds nothing, so a network failure never loses a link, and an episode
    that already has a YouTube and an Apple link is not looked up again. Episodes still without a link of their own are printed
    as a warning, never an error. `resolver` is a function(rows) -> dict; None means the real lookup unless SIGMA_NO_LINK_LOOKUP is
    set; False skips it."""
    found = {e["episode_id"]: {k: e[k] for k in LINK_KEYS if e.get(k)} for e in previous if e.get("episode_id")}
    if resolver is False or (resolver is None and os.environ.get("SIGMA_NO_LINK_LOOKUP")):
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


def _export_claims(run_dir: Path, run_name: str, found: dict) -> list[dict]:
    from . import library

    with tempfile.TemporaryDirectory(prefix="sigma-publication-check-") as temp:
        db = Path(temp) / "library.sqlite"
        library.ingest_run(run_dir, db=db, transcripts=False, include_reused_claims=True)
        rows = []
        for row in library.query_claims(db=db, limit=0):
            row.pop("transcript_path", None)
            row["run"] = run_name
            youtube = found.get(row.get("episode_id"), {}).get("youtube_url")
            if youtube and not row.get("youtube_url"):
                row["youtube_url"], row["link"] = youtube, library.ts_link(youtube, row.get("timestamp"))
            rows.append(row)
    return rows


def _valid_cached_link(kind: str, url: str, spotify_kind: str | None = None) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return False
    except ValueError:
        return False
    if kind == "youtube_url":
        from .links import yt_id

        return parsed.hostname in {"www.youtube.com", "youtube.com", "youtu.be"} and yt_id(url) is not None
    if kind == "apple_url":
        return parsed.hostname == "podcasts.apple.com" and "/podcast/" in parsed.path and "/id" in parsed.path
    if kind == "spotify_url":
        expected = "show" if spotify_kind == "show" else "episode"
        return parsed.hostname == "open.spotify.com" and bool(
            re.fullmatch(rf"/(?:embed/)?{expected}/[A-Za-z0-9]{{22}}", parsed.path))
    return False


def validate_claim_inputs(run_dir: str | Path) -> None:
    """Refuse to publish claims that have not passed their schema and source-grounding checks."""
    from . import ranked, report

    run_dir = Path(run_dir)
    for filename in ("ranked.json", "scores.json", "scores-influencer.json"):
        path = run_dir / filename
        if not path.is_file():
            continue
        data = json.loads(path.read_text())
        ranked.validate(data, ranking=filename == "ranked.json")
        if any(e.get("claims") for e in data.get("episodes", [])):
            errors, warnings = report.ranked_check(data, run_dir)
            problems = [message for _, _, message in errors] + warnings
            if problems:
                raise ValueError(f"[published] {filename} failed claim grounding:\n" + "\n".join(problems[:10]))

    path = run_dir / "report.json"
    if path.is_file():
        data = json.loads(path.read_text())
        report.validate(data, "report")
        if any(any(True for _ in report._cites(e)) for e in data.get("episodes", [])):
            problems = report.verify("report", data, run_dir) + report.warn("report", data, run_dir)
            if problems:
                raise ValueError("[published] report.json failed claim grounding:\n" + "\n".join(problems[:10]))


def validate_publication_inputs(published_root: str | Path, runs_root: str | Path) -> None:
    from . import links

    published_root, runs_root = Path(published_root).resolve(), Path(runs_root).resolve()
    claim_files = ("ranked.json", "scores.json", "scores-influencer.json", "report.json")
    from . import editor

    public_fields = set(EPISODE_KEYS) | set(LINK_KEYS) | set(editor.FIELDS)
    for public_run in sorted(p for p in published_root.iterdir() if p.is_dir()):
        source_run = runs_root / public_run.name
        if not (public_run / "claims.jsonl").is_file() and not any((public_run / f).is_file() for f in claim_files) and \
                not (public_run / "themes.json").is_file() and not (source_run / "themes.json").is_file():
            continue
        if source_run.is_symlink() or not source_run.is_dir() or source_run.resolve().parent != runs_root:
            raise ValueError(f"[published] source run missing for {public_run.name}")
        manifest_path = source_run / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"[published] source manifest missing for {public_run.name}")
        for filename in claim_files:
            public_file, source_file = public_run / filename, source_run / filename
            if public_file.is_file() != source_file.is_file():
                raise ValueError(f"[published] {filename} differs from source run {public_run.name}")
            if public_file.is_file() and public_file.read_bytes() != source_file.read_bytes():
                raise ValueError(f"[published] {filename} differs from source run {public_run.name}")
        try:
            validate_claim_inputs(source_run)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"[published] source claim grounding failed for {public_run.name}") from exc
        edits = editor.load(source_run)
        public_editor, source_editor = public_run / editor.FILE, source_run / editor.FILE
        if public_editor.is_file() != source_editor.is_file() or (public_editor.is_file() and
                (public_editor.is_symlink() or public_editor.read_bytes() != source_editor.read_bytes())):
            raise ValueError(f"[published] editor.json differs from source run {public_run.name}")
        manifest = json.loads(manifest_path.read_text())
        episodes_file = public_run / "episodes.json"
        if not episodes_file.is_file():
            raise ValueError(f"[published] episodes.json missing for {public_run.name}")
        actual_episodes = json.loads(episodes_file.read_text())
        if not isinstance(actual_episodes, list):
            raise ValueError(f"[published] episodes.json differs from source run {public_run.name}")
        manifest_episodes = {e.get("episode_id"): e for e in manifest.get("episodes", []) if isinstance(e, dict)}
        found = {}
        for row in actual_episodes:
            if not isinstance(row, dict) or set(row) - public_fields or not row.get("episode_id"):
                raise ValueError(f"[published] episodes.json has unsupported fields for {public_run.name}")
            episode_id = row["episode_id"]
            source_episode = manifest_episodes.get(episode_id)
            if source_episode is None:
                raise ValueError(f"[published] episodes.json differs from source run {public_run.name}")
            cached = {key: row[key] for key in LINK_KEYS if key in row}
            spotify_kind = cached.get("spotify_kind")
            if spotify_kind is not None and (spotify_kind not in {"show", "episode"} or not cached.get("spotify_url")):
                raise ValueError(f"[published] episodes.json has an invalid link cache for {public_run.name}")
            for key in ("youtube_url", "apple_url", "spotify_url"):
                if key in cached and not _valid_cached_link(key, cached[key], spotify_kind):
                    raise ValueError(f"[published] episodes.json has an invalid link cache for {public_run.name}")
            if source_episode.get("youtube_id") and cached.get("youtube_url") and \
                    links.yt_id(cached["youtube_url"]) != source_episode["youtube_id"]:
                raise ValueError(f"[published] episodes.json has an invalid link cache for {public_run.name}")
            found[episode_id] = cached
        if actual_episodes != episodes(manifest, found, edits):
            raise ValueError(f"[published] episodes.json differs from source run {public_run.name}")
        public_themes, source_themes = public_run / "themes.json", source_run / "themes.json"
        if public_themes.is_file() != source_themes.is_file():
            raise ValueError(f"[published] themes.json differs from source run {public_run.name}")
        if public_themes.is_file():
            if public_themes.is_symlink() or source_themes.is_symlink():
                raise ValueError(f"[published] themes.json differs from source run {public_run.name}")
            from . import themes

            try:
                expected_themes = themes.export(source_run, youtube_urls={
                    row["episode_id"]: row["youtube_url"] for row in actual_episodes if row.get("youtube_url")
                })
                actual_themes = json.loads(public_themes.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"[published] themes.json source check failed for {public_run.name}") from exc
            if actual_themes != expected_themes:
                raise ValueError(f"[published] themes.json differs from source run {public_run.name}")
        claims_file = public_run / "claims.jsonl"
        if not claims_file.is_file():
            raise ValueError(f"[published] claims.jsonl missing for {public_run.name}")
        actual = _read_claims(claims_file)
        expected = _export_claims(source_run, public_run.name, found)
        if actual != expected:
            raise ValueError(f"[published] claims.jsonl differs from validated source run {public_run.name}")


def validate_publication_privacy(published_root: str | Path) -> None:
    from .ranked import private_hits_file

    root = Path(published_root)
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in {".json", ".jsonl", ".md"}):
        if private_hits_file(path):
            raise ValueError(f"[published] public file looks private: {path.relative_to(root)}")


def _copy_x_day(source: Path, target: Path, day: str, edition: bool) -> None:
    scan = source / "scan" / day
    for name in ("manifest.json", "posts.jsonl", "quoted.jsonl"):
        path = scan / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"[published] X source missing for {day}")
        (target / "scan" / day).mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / "scan" / day / name)
    if edition:
        path = source / "days" / day / "edition.json"
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"[published] X edition source missing for {day}")
        (target / "days" / day).mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / "days" / day / path.name)


def _publication_day(value: str) -> bool:
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and datetime.fromisoformat(value).date().isoformat() == value
    except ValueError:
        return False


def _x_stance_source_rows(published_root: Path) -> tuple[set[str], set[str], list[tuple[str, dict]]]:
    from . import stance

    scan_days, sentence_days, source_rows = set(), set(), []
    root = Path(published_root) / "x" / "stances"
    if not root.is_dir():
        return scan_days, sentence_days, source_rows
    for path in sorted(root.glob("*.jsonl")):
        if not _publication_day(path.stem):
            raise ValueError(f"[published] X stance has invalid source filename {path.name}")
        for row in stance.read_jsonl(path):
            key = row.get("key")
            if not isinstance(key, str) or not key:
                raise ValueError(f"[published] X stance has no source key in {path.name}")
            if key.startswith("p-"):
                post_id, event_day = str(row.get("id") or ""), str(row.get("date") or "")
                if key != stance.post_key(post_id) or not post_id.isdigit() or not _publication_day(event_day):
                    raise ValueError(f"[published] X stance source fields are invalid in {path.name}")
                scan_days.add(path.stem)
                source_rows.append((path.stem, row))
            elif key.startswith("x-"):
                day = path.stem
                sentence_days.add(day)
                source_rows.append((day, row))
            else:
                raise ValueError(f"[published] unsupported X stance source key in {path.name}")
    return scan_days, sentence_days, source_rows


def validate_publication_outputs(published_root: str | Path, x_root: str | Path) -> None:
    published_root, x_root = Path(published_root), Path(x_root)
    stance_days, sentence_days, stance_rows = _x_stance_source_rows(published_root)
    scans = stance_days | sentence_days
    sentence_sources = {}
    signal_files = sorted((published_root / "signals").glob("????-??-??.json"))
    if signal_files:
        from . import signals_index
    for f in signal_files:
        day = f.stem
        try:
            actual = json.loads(f.read_text(encoding="utf-8"))
            generated = datetime.fromisoformat(actual["generated_at"])
            expected = signals_index.build(day, published_root, now=generated)
        except (KeyError, OSError, ValueError) as exc:
            raise ValueError(f"[published] Signals source check failed for {day}") from exc
        if problems := signals_index.check(actual, published_root):
            raise ValueError(f"[published] Signals validation failed for {day}: {problems[0]}")
        if actual != expected:
            raise ValueError(f"[published] Signals differ from source labels for {day}")
        if any(row.get("source_kind") == "x" for row in actual.get("signals", [])):
            scans.add(day)

    editions = published_root / "x" / "editions"
    if editions.is_dir():
        from . import xdaily

        for f in sorted(editions.glob("*.json")):
            day = f.stem
            try:
                actual = json.loads(f.read_text(encoding="utf-8"))
                source = json.loads((x_root / "days" / day / "edition.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"[published] X edition source check failed for {day}") from exc
            allow_empty_signals = not actual.get("signals") and bool(actual.get("posts") or actual.get("more"))
            errors, _ = xdaily.edition_problems(day, source, allow_empty_signals=allow_empty_signals)
            if errors:
                raise ValueError(f"[published] X edition failed source grounding for {day}: {errors[0]}")
            expected = xdaily.public_edition(day, source)
            if actual != expected:
                raise ValueError(f"[published] X edition differs from source for {day}")
            sentence_sources[day] = source
            scans.add(day)

    if scans:
        from . import board, stance, xdaily

    posts_by_day, thread_members_by_day = {}, {}
    for day in sorted(stance_days):
        posts = xdaily.read_jsonl(x_root / "scan" / day / "posts.jsonl")
        posts_by_day[day] = {str(p.get("id")): p for p in posts}
        roots = stance._thread_roots(posts)
        members = {}
        for post_id, root_id in roots.items():
            if post_id != root_id:
                members.setdefault(root_id, []).append(post_id)
        for member_ids in members.values():
            member_ids.sort(key=lambda post_id: (str(posts_by_day[day][post_id].get("created_at") or ""),
                                                 len(post_id), post_id))
        thread_members_by_day[day] = members
    for day, row in stance_rows:
        if not str(row.get("key", "")).startswith("p-"):
            continue
        post_id = str(row.get("id") or "")
        post = posts_by_day[day].get(post_id)
        thread = row.get("thread")
        source_thread = thread_members_by_day[day].get(post_id, [])
        thread_set = set(thread) if isinstance(thread, list) and all(isinstance(item, str) for item in thread) else set()
        valid_thread = (
            isinstance(thread, list) and bool(thread) and
            all(isinstance(item, str) and item.isdigit() for item in thread) and
            len(set(thread)) == len(thread) and
            [item for item in source_thread if item in thread_set] == thread
        ) if "thread" in row else True
        if (row.get("key") != stance.post_key(post_id) or post is None or
                row.get("handle") != post.get("handle") or
                row.get("date") != stance._pacific_day(post.get("created_at"), board.pacific_tz()) or
                not valid_thread):
            raise ValueError(f"[published] X stance source mismatch for {day}")
    if sentence_days:
        from . import stance, tickers

        for day in sorted(sentence_days):
            source = sentence_sources.get(day)
            if source is None:
                raise ValueError(f"[published] X sentence stance source missing for {day}")
            keys = {item["key"] for item in stance.x_items(source, tickers.load())}
            for row_day, row in stance_rows:
                if row_day == day and str(row.get("key", "")).startswith("x-") and row["key"] not in keys:
                    raise ValueError(f"[published] X sentence stance source mismatch for {day}")


def freeze_publication_inputs(data_root: str | Path, snapshot_root: str | Path) -> None:
    data_root, snapshot_root = Path(data_root).resolve(), Path(snapshot_root).resolve()
    (snapshot_root / "published").mkdir(parents=True, exist_ok=True)
    for name in ("published", "creators.json", "entities.json", "people.yaml", "sources.yaml", "show_links.yaml",
                 "x-accounts.json", "research"):
        source = data_root / name
        if source.is_symlink() or (source.is_dir() and any(path.is_symlink() for path in source.rglob("*"))):
            raise ValueError(f"[published] symlink in publication input {name}")
        if source.is_dir():
            shutil.copytree(source, snapshot_root / name, dirs_exist_ok=True)
        elif source.is_file():
            (snapshot_root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, snapshot_root / name)
    site_config = Path(os.environ.get("SIGMA_SITE_CONFIG") or data_root / "site.json").expanduser().resolve()
    if site_config.is_file():
        shutil.copy2(site_config, snapshot_root / "site.json")
    x_source = Path(os.environ.get("SIGMA_X_DIR") or data_root / "x").expanduser().resolve()
    validate_publication_privacy(snapshot_root / "published")
    runs = data_root / "runs"
    for public_run in sorted(p for p in (snapshot_root / "published").iterdir() if p.is_dir()):
        claim_files = ("ranked.json", "scores.json", "scores-influencer.json", "report.json")
        source_run = runs / public_run.name
        if not (public_run / "claims.jsonl").is_file() and not any((public_run / f).is_file() for f in claim_files) and \
                not (public_run / "themes.json").is_file() and not (source_run / "themes.json").is_file():
            continue
        if source_run.is_symlink() or not source_run.is_dir() or source_run.resolve().parent != runs.resolve():
            raise ValueError(f"[published] source run missing for {public_run.name}")
        dest_run = snapshot_root / "runs" / public_run.name
        dest_run.mkdir(parents=True, exist_ok=True)
        manifest = source_run / "manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError(f"[published] source manifest missing for {public_run.name}")
        shutil.copy2(manifest, dest_run / manifest.name)
        for filename in claim_files:
            if (public_run / filename).is_file():
                source = source_run / filename
                if source.is_symlink() or not source.is_file():
                    raise ValueError(f"[published] {filename} missing from source run {public_run.name}")
                shutil.copy2(source, dest_run / filename)
        editor_source = source_run / "editor.json"
        if editor_source.is_file():
            if editor_source.is_symlink():
                raise ValueError(f"[published] editor.json missing from source run {public_run.name}")
            shutil.copy2(editor_source, dest_run / "editor.json")
        theme_source = source_run / "themes.json"
        if theme_source.is_file():
            if theme_source.is_symlink():
                raise ValueError(f"[published] themes.json missing from source run {public_run.name}")
            shutil.copy2(theme_source, dest_run / theme_source.name)
        data = json.loads(manifest.read_text())
        cited_episodes = set()
        if editor_source.is_file():
            cited_episodes.update(e["episode_id"] for e in json.loads(editor_source.read_text())["episodes"])
        for filename in claim_files:
            source = source_run / filename
            if not source.is_file():
                continue
            for episode in json.loads(source.read_text()).get("episodes", []):
                if (episode.get("claims") or episode.get("signal") or
                        any(section.get("claims") for section in episode.get("sections", []))):
                    if episode.get("episode_id"):
                        cited_episodes.add(episode["episode_id"])
        for episode in data.get("episodes", []):
            if episode.get("episode_id") not in cited_episodes:
                continue
            filename = episode.get("file")
            if not filename:
                continue
            source = (source_run / filename).resolve()
            if source.parent != source_run.resolve() and source_run.resolve() not in source.parents:
                raise ValueError(f"[published] transcript path escapes source run {public_run.name}")
            if source.is_file():
                target = dest_run / source.relative_to(source_run.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    validate_publication_inputs(snapshot_root / "published", snapshot_root / "runs")
    edition_dir = snapshot_root / "published" / "x" / "editions"
    edition_days = {p.stem for p in edition_dir.glob("*.json")} if edition_dir.is_dir() else set()
    stance_days, sentence_days, _ = _x_stance_source_rows(snapshot_root / "published")
    signal_days = {p.stem for p in (snapshot_root / "published" / "signals").glob("????-??-??.json")}
    x_signal_days = set()
    for path in (snapshot_root / "published" / "signals").glob("????-??-??.json"):
        day = json.loads(path.read_text(encoding="utf-8"))
        if any(row.get("source_kind") == "x" for row in day.get("signals", [])):
            x_signal_days.add(path.stem)
    x_days = x_signal_days | edition_days | stance_days | sentence_days
    if x_days and not x_source.is_dir():
        raise ValueError("[published] X source root missing")
    for day in sorted(x_days | {day for day in signal_days if (x_source / "scan" / day / "manifest.json").is_file()}):
        _copy_x_day(x_source, snapshot_root / "x", day, day in edition_days)
    previous = {key: os.environ.get(key) for key in ("SIGMA_DATA_ROOT", "SIGMA_X_DIR", "SIGMA_SITE_CONFIG")}
    os.environ.update(SIGMA_DATA_ROOT=str(snapshot_root), SIGMA_X_DIR=str(snapshot_root / "x"),
                      SIGMA_SITE_CONFIG=str(snapshot_root / "site.json"))
    try:
        validate_publication_outputs(snapshot_root / "published", snapshot_root / "x")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
    from . import editor, themes

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
    from .ranked import private_hits_file

    for p in srcs:  # before anything is replaced: a private phrase in any file stops the export
        if p.suffix in (".md", ".json", ".jsonl") and (hits := private_hits_file(p)):
            raise ValueError(f"[published] {p.name} looks private ({hits}); fix it in the run folder, never in published/")
        if p.name == editor.FILE and p.stat().st_size > MAX_BYTES:
            raise ValueError(f"[published] editor.json exceeds the {MAX_BYTES // 1000} KB publication limit")
    validate_claim_inputs(run_dir)
    edits = editor.load(run_dir)
    found = resolve_links(run_dir, manifest, previous, resolver)
    youtube = {e["episode_id"]: u for e in episodes(manifest, found) if (u := e.get("youtube_url"))}
    resolved_themes = themes.export(run_dir, top=top, youtube_urls=youtube)
    rows = _export_claims(run_dir, dest.name, found)
    if problems := restated_problems(rows, f"published/{dest.name}"):  # the publish gate: ingest merges these, so this means a bug
        raise ValueError("[published] the same point is listed twice:\n" + "\n".join(problems[:10]))
    stances = dest / STANCES  # labels (stance.py) are made after the export and outlive it: a re-export keeps them
    kept = stances.read_bytes() if stances.is_file() else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    try:
        if kept is not None:
            (stage / STANCES).write_bytes(kept)
        written, skipped = [], []
        for p in srcs:
            if p.stat().st_size > MAX_BYTES:
                skipped.append(p.name)
                continue
            shutil.copy2(p, stage / p.name)
            written.append(p.name)
        if man.exists():
            (stage / "episodes.json").write_text(json.dumps(episodes(manifest, found, edits), indent=1, ensure_ascii=False) + "\n")
            written.append("episodes.json")
        (stage / "claims.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        written.append("claims.jsonl")
        if resolved_themes:
            (stage / themes.FILE).write_text(json.dumps(resolved_themes, indent=1, ensure_ascii=False) + "\n")
            written.append(themes.FILE)
        for p in stage.iterdir():
            if p.is_file() and p.suffix in (".md", ".json", ".jsonl"):
                if hits := private_hits_file(p):
                    raise ValueError(f"[published] {p.name} looks private ({hits}); fix it before export")
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(stage, dest)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    for s in skipped:
        print(f"[published] skipped {s}: over {MAX_BYTES // 1000} KB")
    return dest, written
