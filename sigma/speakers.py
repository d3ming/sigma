"""Who speaks in an episode, recorded as `speakers` on the run's manifest row.

Only a reader names a speaker: it has read the whole transcript, and a name in the title or description is as often a person
discussed as a person heard. The reader's `speakers` ({name, role}, in rank/*-out.json) are checked against the episode's own
text. A name on the follow list (people.yaml, by name or alias) gets that entry's profile: role, kind, links and fund. An
unlisted guest keeps the reader's role only when its words are in the description or transcript. Nothing here reads or
stores holdings: a fund is a name and an SEC CIK. Importable without third-party packages, because the site renders these rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

KINDS = ("operator", "fund manager", "analyst", "researcher", "commentator", "host")
STOP = {"a", "an", "and", "at", "for", "in", "of", "the", "to", "with"}


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def clean_cik(cik) -> str | None:
    """The CIK as the ten digits EDGAR prints, or None when unconfirmed. Only a string of ten digits is accepted: YAML reads
    an unquoted 0001234567 as an octal number, a different filer."""
    if cik is None:
        return None
    if not isinstance(cik, str) or not re.fullmatch(r"\d{10}", cik) or int(cik) == 0:
        raise ValueError(f"cik must be a quoted string of 10 digits: {cik!r}")
    return cik


def edgar_url(cik) -> str:
    return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={clean_cik(cik)}&type=13F-HR"


def check_profile(name: str, kind, links, fund) -> None:
    if kind is not None and kind not in KINDS:
        raise ValueError(f"{name}: kind must be one of {', '.join(KINDS)}")
    for link in links or []:
        parts = urlsplit(str(link.get("url", ""))) if isinstance(link, dict) else None
        if not parts or set(link) != {"label", "url"} or not str(link["label"]).strip() or parts.scheme != "https" or not parts.hostname:
            raise ValueError(f"{name}: each link is {{label, url}} with an https url")
    if fund is not None:
        if not isinstance(fund, dict) or set(fund) - {"name", "cik"} or not str(fund.get("name", "")).strip():
            raise ValueError(f"{name}: fund is {{name, cik}} only; holdings never live here")
        try:
            clean_cik(fund.get("cik"))
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc


def profile_row(person) -> dict:
    row = {"name": person.name, "role": person.role, "kind": person.kind,
           "links": [dict(link) for link in person.links],
           "fund": {"name": person.fund["name"], "cik": clean_cik(person.fund.get("cik"))} if person.fund else None}
    return {k: v for k, v in row.items() if v}


def role_grounded(role: str, hay: str) -> bool:
    words = [w for w in norm(role).split() if w not in STOP]
    return bool(words) and all(f" {w} " in hay for w in words)


def speakers_of(raw, people, title, description, transcript: str, source: str) -> list[dict]:
    """The reader's speakers as manifest rows. `raw` is a list of {name, role} (a bare string is a name); `source` names the file
    it came from. A name the episode's own text does not contain in full, or a first name alone, stops the work."""
    listed = {norm(n): p for p in people for n in p.names}
    text, described = f" {norm(f'{title} {description} {transcript}')} ", f" {norm(f'{description} {transcript}')} "
    out: list[dict] = []
    for g in raw or []:
        if isinstance(g, str):
            g = {"name": g}
        if not isinstance(g, dict) or not isinstance(g.get("name"), str) or not isinstance(g.get("role") or "", str):
            raise ValueError(f"{source}: a speaker is a name or {{name, role}} with text values, not {g!r}")
        name, role = " ".join(g["name"].split()), " ".join((g.get("role") or "").split())
        if len(norm(name).split()) < 2:
            raise ValueError(f"{source}: speaker {name!r} needs a full name")
        if f" {norm(name)} " not in text:
            raise ValueError(f"{source}: speaker {name!r} is not in the title, description or transcript")
        person = listed.get(norm(name))
        row = profile_row(person) if person else {"name": name, **({"role": role} if role_grounded(role, described) else {})}
        if norm(row["name"]) not in {norm(o["name"]) for o in out}:
            out.append({**row, "matched_by": "rank"})
    return out


def record_run(run_dir: str | Path, people) -> dict:
    """Write `speakers` onto every manifest row of the run from the readers' rank/*-out.json. An episode no reader named speakers
    for keeps the ones an earlier merge recorded (its score was reused). Returns {"episodes": n, "named": n with a speaker}."""
    from . import manifest

    run_dir = Path(run_dir)
    reader: dict[str, tuple[str, list]] = {}
    for f in sorted((run_dir / "rank").glob("*-out.json")):
        rows = json.loads(f.read_text())
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError(f"{f.name}: a reader output is a JSON list of episode objects")
        for r in rows:
            if r.get("speakers") is not None:
                if not isinstance(r["speakers"], list):
                    raise ValueError(f"{f.name}: speakers is a list")
                reader[r.get("episode_id")] = (f.name, r["speakers"])
    stat = {"episodes": 0, "named": 0}

    def apply(man: dict) -> None:
        for e in man.get("episodes", []):
            transcript = ""
            if e.get("file") and (run_dir / e["file"]).is_file():
                transcript = (run_dir / e["file"]).read_text()
            source, raw = reader.get(e["episode_id"]) or (
                "manifest.json", [s for s in e.get("speakers") or [] if s.get("matched_by") == "rank"])
            rows = speakers_of(raw, people, e.get("title"), e.get("description"), transcript, f"{source} {e['episode_id']}")
            stat["episodes"] += 1
            stat["named"] += bool(rows)
            if rows:
                e["speakers"] = rows
            else:
                e.pop("speakers", None)

    manifest.update(run_dir / "manifest.json", apply)
    return stat


def safe(episode_id: str) -> str:
    return episode_id.replace(":", "_")


def read_run(run_dir: str | Path, ids: list[str] | None = None, jobs: int = 4) -> list[str]:
    """Have Codex read each episode's description and whole transcript (prompts/speakers.md) and write rank/speakers-<id>-out.json,
    for the episodes that have a transcript and no such file yet, or just `ids`. Returns the ids it read. Run `record_run` after."""
    from concurrent.futures import ThreadPoolExecutor

    from . import edit

    run_dir = Path(run_dir)
    rank = run_dir / "rank"
    rank.mkdir(exist_ok=True)
    man = json.loads((run_dir / "manifest.json").read_text())
    todo = [e for e in man["episodes"] if e.get("file") and (run_dir / e["file"]).is_file()
            and (e["episode_id"] in ids if ids else not (rank / f"speakers-{safe(e['episode_id'])}-out.json").exists())]
    template = (edit.ROOT / "prompts" / "speakers.md").read_text()
    model, effort, _ = edit.agent()

    def one(e: dict) -> str:
        out = rank / f"speakers-{safe(e['episode_id'])}-out.json"
        out.unlink(missing_ok=True)
        facts = {"episode_id": e["episode_id"], "title": e.get("title") or "", "description": e.get("description") or "",
                 "transcript": (run_dir / e["file"]).resolve(), "out": out.resolve()}
        failure = edit.codex(template.format(**facts), rank, rank / f"speakers-{safe(e['episode_id'])}.log")
        if failure or not out.is_file():
            raise RuntimeError(f"{e['episode_id']}: {failure or 'the reader wrote no output'}")
        return e["episode_id"]

    print(f"[speakers] {len(todo)} episode(s) to read with {model} ({effort}), {jobs} at a time")
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, todo))
