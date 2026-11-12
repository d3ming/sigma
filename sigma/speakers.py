"""Who speaks in an episode, recorded as `speakers` on the run's manifest row.

A person on the follow list (people.yaml) is matched by name or alias in the title, the description or the opening of the
transcript. A guest who is not on the list comes from the reader that scored the episode (prompts/rank.md) and must
appear in the title, description or transcript. Nothing here reads or stores holdings: a fund is a name and an SEC CIK.
Importable without third-party packages, because the site renders these rows.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

KINDS = ("operator", "fund manager", "analyst", "researcher", "commentator", "host")
OPENING = 3000


def norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def clean_cik(cik) -> str | None:
    """A CIK as the ten digits EDGAR prints, or None when unconfirmed."""
    if cik in (None, ""):
        return None
    s = str(cik).strip()
    if not s.isdigit() or int(s) == 0 or len(s) > 10:
        raise ValueError(f"cik must be up to ten digits: {cik!r}")
    return s.zfill(10)


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


def transcript_opening(text: str) -> str:
    body = text.split("\n---\n", 1)[1] if text.startswith("---") and "\n---\n" in text else text
    return body[:OPENING]


def identify(people, title, description, show, transcript: str = "") -> list[dict]:
    from .people import mentions, on_topic

    opening = transcript_opening(transcript)
    rows = []
    for p in people:
        if not on_topic(p, title or "", description or "", show or ""):
            continue
        where = next((w for w, t in (("title", title), ("description", description), ("transcript", opening)) if mentions(p, t)), None)
        if where:
            rows.append({**profile_row(p), "matched_by": where})
    return rows


def guests(raw, people, listed: list[dict], text: str) -> list[dict]:
    """The reader's `speakers` that the list did not already name. A name the episode's own text never contains stops the work."""
    known = {norm(n) for p in people for n in p.names} | {norm(r["name"]) for r in listed}
    hay = f" {norm(text)} "
    out = []
    for g in raw or []:
        name, role = " ".join(str(g.get("name", "")).split()), " ".join(str(g.get("role", "")).split())
        if not name:
            raise ValueError("a speaker has no name")
        if f" {norm(name)} " not in hay:
            raise ValueError(f"speaker {name!r} is not in the title, description or transcript")
        if norm(name) not in known and norm(name) not in {norm(o["name"]) for o in out}:
            out.append({"name": name, **({"role": role} if role else {}), "matched_by": "rank"})
    return out


def record_run(run_dir: str | Path, people) -> dict:
    """Write `speakers` onto every manifest row of the run. Reader speakers come from rank/*-out.json; an episode whose score
    was reused keeps the ones an earlier merge recorded. Returns {"episodes": n, "named": n with a speaker, "guests": n}."""
    from . import manifest

    run_dir = Path(run_dir)
    reader = {}
    for f in sorted((run_dir / "rank").glob("*-out.json")):
        for r in json.loads(f.read_text()):
            if r.get("speakers"):
                reader[r["episode_id"]] = r["speakers"]
    stat = {"episodes": 0, "named": 0, "guests": 0}

    def apply(man: dict) -> None:
        for e in man.get("episodes", []):
            transcript = ""
            if e.get("file") and (run_dir / e["file"]).is_file():
                transcript = (run_dir / e["file"]).read_text()
            listed = identify(people, e.get("title"), e.get("description"), e.get("source"), transcript)
            raw = reader.get(e["episode_id"]) or [s for s in e.get("speakers") or [] if s.get("matched_by") == "rank"]
            extra = guests(raw, people, listed, f"{e.get('title')} {e.get('description')} {transcript}")
            rows = listed + extra
            stat["episodes"] += 1
            stat["named"] += bool(rows)
            stat["guests"] += len(extra)
            if rows:
                e["speakers"] = rows
            else:
                e.pop("speakers", None)

    manifest.update(run_dir / "manifest.json", apply)
    return stat
