"""Creators: one person or channel, and the outlets Wire reads them on.

`creators.json` (repo root, public) lists each creator with the `sources` (ids in sources.yaml) and X `x` handles (in
x-accounts.json) that are theirs. It is its own file, not a key of entities.json: outside contributors propose it in pull
requests like the two lists it points into, and its references are checked against those lists, not against topics and
companies. A newsletter, a paid site or any other outlet that stays private is kept in data/creators-private.json, which
only wire.calls reads. Nothing here may import wire.calls: the site builds from this file and must not be able to reach a
creator's track record.

Standard library only at import, because the site host builds with nothing else.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CREATORS_FILE = ROOT / "creators.json"
SOURCES_FILE = ROOT / "sources.yaml"
X_ACCOUNTS_FILE = ROOT / "x-accounts.json"


@dataclass
class Creator:
    id: str
    name: str
    sources: list[str] = field(default_factory=list)  # ids in sources.yaml
    x: list[str] = field(default_factory=list)        # handles in x-accounts.json
    hosts: list[str] = field(default_factory=list)    # names the show's own hosts go by, when the creator's name is not one (calls.py)


def read_raw(path: Path | None = None) -> dict:
    try:
        d = json.loads(Path(path or CREATORS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def load(path: Path | None = None) -> list[Creator]:
    """The creators in the file. A missing or broken file gives none, so the site still builds; `problems` says what is wrong."""
    out = []
    for c in read_raw(path).get("creators") or []:
        if isinstance(c, dict) and c.get("id") and c.get("name"):
            out.append(Creator(str(c["id"]), str(c["name"]), [str(s) for s in c.get("sources") or []], [str(h) for h in c.get("x") or []],
                            [str(h) for h in c.get("hosts") or []]))
    return out


def norm_show(name) -> str:
    """A show name as compared across feeds, YouTube and claims: lower case, letters and digits, single spaces."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split())


def source_names(path: Path = SOURCES_FILE) -> dict[str, list[str]]:
    """{source id: [name, *aliases]} from sources.yaml. The site host has no YAML parser; every source is one flow-style line."""
    try:
        import yaml
    except ImportError:
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"\s*- \{.*?\bid: ([\w-]+).*?\bname: (\"[^\"]*\"|[^,}]+)", line):
                al = re.search(r"\baliases: \[([^\]]*)\]", line)
                names = [json.loads(m[2]) if m[2].startswith('"') else m[2].strip()]
                names += [q or b.strip() for q, b in re.findall(r'"([^"]*)"|([^,"]+)', al[1])] if al else []
                out[m[1]] = names
        return out
    return {s["id"]: [s["name"], *(s.get("aliases") or [])] for s in yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]}


def x_handles(path: Path = X_ACCOUNTS_FILE) -> list[str]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a["handle"] for a in d.get("accounts") or [] if isinstance(a, dict) and a.get("handle")]


def problems(raw: dict, source_ids, handles) -> list[str]:
    """Broken references in creators.json: a source id not in sources.yaml, a handle not in x-accounts.json, an id or an
    outlet listed twice. The loader keeps them quietly, so the check says them out loud."""
    ids, known_x = set(source_ids), {h.lower() for h in handles}
    seen: dict[str, str] = {}
    out = []
    for c in raw.get("creators") or []:
        cid = c.get("id")
        if not (cid and c.get("name")):
            out.append(f"creator without an id and a name: {c}")
            continue
        if f"id:{cid}" in seen:
            out.append(f"{cid}: listed twice")
        seen[f"id:{cid}"] = cid
        for s in c.get("sources") or []:
            if s not in ids:
                out.append(f'{cid}: source "{s}" is not in sources.yaml')
            elif seen.setdefault(f"source:{s}", cid) != cid:
                out.append(f'{cid}: source "{s}" is already {seen[f"source:{s}"]}\'s')
        for h in c.get("x") or []:
            if h.lower() not in known_x:
                out.append(f'{cid}: X handle "{h}" is not in x-accounts.json')
            elif seen.setdefault(f"x:{h.lower()}", cid) != cid:
                out.append(f'{cid}: X handle "{h}" is already {seen[f"x:{h.lower()}"]}\'s')
    return out


def check(path: Path | None = None) -> list[str]:
    """`problems` for the real files."""
    return problems(read_raw(path), source_names(), x_handles())
