"""Topics, companies, people and the lenses that group episodes on the site.

`data/entities.json` holds what people curate: the topic list, each show's topics, companies with aliases and
topics, people with company and role, and the lens rules. It is JSON because the Vercel build has no YAML parser.
Everything else is derived from published claims by `sigma.site`: a claim ticker names a company, a named speaker may have
a curated company, and a lens is a rule over an episode's show topics and companies.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .paths import data_root

ENTITIES_FILE = data_root() / "entities.json"
NEW_NAME_MIN_CLAIMS = 3  # `sigma entities check` lists names with this many claims and no entry


def slug(s: str) -> str:
    a = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", a).strip("-")


@dataclass
class Entities:
    groups: list[dict] = field(default_factory=list)      # [{id, name, topics: [topic id]}]
    topic_names: dict = field(default_factory=dict)       # topic id -> label
    show_topics: dict = field(default_factory=dict)       # show slug -> [topic id]
    companies: dict = field(default_factory=dict)         # company id -> {name, kind, ticker?, aliases?, topics?}
    people: dict = field(default_factory=dict)            # person slug -> {name, affiliations: [{company, role, from?, to?}]}
    lenses: dict = field(default_factory=dict)            # lens id -> {name, mark, about, topics, public_ticker?}
    by_key: dict = field(default_factory=dict)            # lowercased ticker or alias -> company id


def load(path: Path | None = None) -> Entities:
    """Read entities.json. A missing or broken file gives an empty set, so the site still builds."""
    try:
        d = json.loads(Path(path or ENTITIES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    names = d.get("topic_names") or {}
    groups = [{"id": g.get("id"), "name": g.get("name") or g.get("id"),
               "topics": [t for t in g.get("topics") or [] if t in names]} for g in d.get("topic_groups") or []]
    ent = Entities(groups=[g for g in groups if g["topics"]], topic_names=names,
                   show_topics={k: [t for t in v if t in names] for k, v in (d.get("show_topics") or {}).items()},
                   companies=d.get("companies") or {}, people=d.get("people") or {}, lenses=d.get("lenses") or {})
    for cid, c in ent.companies.items():
        for key in [c.get("ticker"), c.get("name"), *(c.get("aliases") or [])]:
            if key:
                ent.by_key.setdefault(str(key).lower(), cid)
    return ent


def resolve_ticker(ent: Entities, t: str) -> tuple[str, str, bool]:
    """(company id, name, curated) for a claim ticker. `private:OpenAI` and `NVDA` map to a curated company when one has
    that ticker, name or alias; any other ticker gets an automatic company, so no tagged company is lost."""
    cid = ent.by_key.get(t.lower())
    if cid:
        return cid, ent.companies[cid].get("name") or cid, True
    name = t[8:] if t.lower().startswith("private:") else t
    return slug(name), name, False


def affiliation(ent: Entities, person_slug: str) -> tuple[str, str] | None:
    """(company id, role) of the person's current affiliation, if the file has one."""
    p = ent.people.get(person_slug) or {}
    for a in p.get("affiliations") or []:
        if not a.get("to") and a.get("company") in ent.companies:
            return a["company"], a.get("role") or ""
    return None


def lenses_of(ent: Entities, topics: list[str], company_ids: list[str], public_claims: int, roles: list[str] = ()) -> list[str]:
    """Lenses an episode belongs to. A lens takes the episode when its show's topics or a mentioned company's topics meet the
    lens `topics`, when the lens sets `public_ticker` (a number of claims; true means 1) and that many claims name a public
    ticker, or when a speaker's role or the title matches one of the lens `roles` patterns. An episode can hold more than one
    lens or none. To change a lens, edit its `topics`, `roles` or `public_ticker` in entities.json."""
    have = set(topics) | {t for c in company_ids for t in (ent.companies.get(c) or {}).get("topics") or []}
    return [lid for lid, lens in ent.lenses.items()
            if have & set(lens.get("topics") or [])
            or any(re.search(rx, r, re.I) for rx in lens.get("roles") or [] for r in roles)
            or (lens.get("public_ticker") and public_claims >= int(lens["public_ticker"]))]


def title_hits(ent: Entities, title: str, min_len: int = 4) -> list[str]:
    """Curated companies whose name or alias appears in the text as a whole word (names under `min_len` letters are skipped:
    in a title "AMD" or "ARM" is too often another word; in a speaker's role it is the company)."""
    out = []
    for cid, c in ent.companies.items():
        for key in [c.get("name"), *(c.get("aliases") or [])]:
            if key and len(key) >= min_len and not str(key).lower().startswith("private:") \
                    and re.search(r"(?<![A-Za-z0-9])" + re.escape(str(key)) + r"(?![A-Za-z0-9])", title, re.I):
                out.append(cid)
                break
    return out


def unknown_names(ent: Entities, claims: list[dict], min_claims: int = NEW_NAME_MIN_CLAIMS) -> dict:
    """Names with `min_claims` or more claims and no curated entry: {"companies": [(name, claims)], "people": [(name, claims)]}.
    A person counts when the file has no affiliation for them. `claims` are enriched claims (see sigma.site.enrich)."""
    cos: Counter = Counter()
    ppl: Counter = Counter()
    for c in claims:
        for t in c.get("tickers") or []:
            _, name, curated = resolve_ticker(ent, t)
            if not curated:
                cos[name] += 1
        if c.get("person") and not affiliation(ent, slug(c["person"])):
            ppl[c["person"]] += 1
    return {"companies": [(n, k) for n, k in cos.most_common() if k >= min_claims],
            "people": [(n, k) for n, k in ppl.most_common() if k >= min_claims]}


# ---------------------------------------------------------------- commands: sigma entities check | backfill

def _published_claims(published: Path):
    """(runs, episode registry, enriched claims, people) for the checks, reading published/ as `sigma site` does."""
    from . import site

    runs = site.load_runs(published)
    people = site.enrich(runs)
    reg = site.build_episodes(runs)
    return site, runs, reg, people


def problems(raw: dict) -> list[str]:
    """Broken references in the raw file; the loader drops these quietly, so the check says them out loud."""
    names, cos = raw.get("topic_names") or {}, raw.get("companies") or {}
    out = []
    for show, tops in (raw.get("show_topics") or {}).items():
        out += [f'show_topics.{show}: unknown topic "{t}"' for t in tops if t not in names]
    for g in raw.get("topic_groups") or []:
        out += [f'topic_groups.{g.get("id")}: unknown topic "{t}"' for t in g.get("topics") or [] if t not in names]
    for lid, lens in (raw.get("lenses") or {}).items():
        out += [f'lenses.{lid}: unknown topic "{t}"' for t in lens.get("topics") or [] if t not in names]
    for cid, c in cos.items():
        out += [f'companies.{cid}: unknown topic "{t}"' for t in c.get("topics") or [] if t not in names]
    for ps, p in (raw.get("people") or {}).items():
        out += [f'people.{ps}: unknown company "{a.get("company")}"' for a in p.get("affiliations") or [] if a.get("company") not in cos]
    return out


def check_cmd(args) -> None:
    """List what entities.json is missing: names with 3+ claims and no entry, shows with no topic. Exit 1 on broken references, in entities.json or in creators.json (its sources and X handles)."""
    path = Path(args.file or ENTITIES_FILE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"[entities] cannot read {path}: {e}")
    ent = load(path)
    site, runs, reg, _ = _published_claims(Path(args.published))
    from . import creators

    bad = problems(raw) + [f"creators.json: {b}" for b in creators.check()]
    new = unknown_names(ent, [c for r in runs for c in site.uniq_claims(r["claims"])])
    shows = sorted({e["show"] for e in reg.values() if e["claims"] and e["show"] and not ent.show_topics.get(site.person_slug(e["show"]))})
    for b in bad:
        print(f"[entities] problem: {b}")
    for n, k in new["companies"]:
        print(f'[entities] new company: "{slug(n)}": {{"name": "{n}", "kind": "private"}}  ({k} claims)')
    for n, k in new["people"]:
        print(f'[entities] person with no company: "{slug(n)}"  ({k} claims; `sigma entities backfill` suggests one from their role)')
    for s in shows:
        print(f'[entities] show with no topic: "{site.person_slug(s)}"  ({s})')
    print(f"[entities] {len(bad)} problems, {len(new['companies'])} new companies, {len(new['people'])} people without a company, "
          f"{len(shows)} shows without a topic")
    if bad:
        raise SystemExit(1)


def backfill_cmd(args) -> None:
    """Suggest a company for each person without one, from the role the claims gave ("Amazon CEO" -> Amazon, CEO). --write adds
    them to entities.json; a person who already has an entry is never touched."""
    path = Path(args.file or ENTITIES_FILE)
    raw = json.loads(path.read_text(encoding="utf-8"))
    ent = load(path)
    _, _, _, people = _published_claims(Path(args.published))
    found = {}
    for ps, p in sorted(people.items()):
        if ps in (raw.get("people") or {}):
            continue
        for role, _ in p["roles"].most_common():
            hits = title_hits(ent, role, 3)
            if len(hits) == 1:
                name = ent.companies[hits[0]].get("name") or hits[0]
                left = re.sub(re.escape(name), "", role, flags=re.I).strip(" ,;:-()/")
                left = re.sub(r"^(of|at|from)\s+|\s+(of|at|from)$", "", left, flags=re.I).strip(" ,;:-()/")
                found[ps] = {"name": p["name"], "affiliations": [{"company": hits[0], "role": left}]}
                break
    for ps, v in found.items():
        a = v["affiliations"][0]
        print(f'[entities] {v["name"]} -> {a["company"]}' + (f' ({a["role"]})' if a["role"] else ""))
    if args.write and found:
        raw.setdefault("people", {}).update(found)
        path.write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[entities] {len(found)} suggested" + (f", written to {path.name}" if args.write and found else "; run with --write to add them"))
