from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "ranked.schema.json"
# Field names of a holdings ledger. Only keys are checked: a poster's own public weights or positions are reportable prose.
FORBIDDEN = ("holding", "weight", "market_pct", "folio")
# Prose that only the owner's private material carries: the publisher's own ("our", "the owner's", "the maintainer's")
# portfolio, positions, sizes, allocation or cost basis, money we moved, a local home path. A position or weight a poster
# states publicly about themselves ("my portfolio is ...", "a 10% position") is a claim to attribute, not a leak, so
# first-person singular and generic words such as "portfolio weights" are not blocked. Checked on every file that is
# published, not only on JSON keys (a holdings note pasted into a digest has no "holding" key).
PRIVATE = re.compile(
    r"\b(?:our|the\s+owner'?s|the\s+maintainer'?s)\s+(?:portfolio|holdings?|positions?|allocations?|weights?|book"
    r"|position\s+sizes?|cost\s+basis|unrealized)\b"
    r"|%\s+of\s+(?:our|the\s+owner'?s|the\s+maintainer'?s)\s+portfolio\b"
    r"|\bwe\s+(?:own|hold|bought|sold|trimmed|added\s+to)\s+(?:shares|\$?[A-Z]{1,5}\b)"
    r"|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/", re.I)

PEM_PRIVATE_KEY = re.compile(r"-----BEGIN (?:(?:ENCRYPTED|RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----", re.I)
SECRET_VALUE = re.compile(r"\bvercel_blob_rw_[a-z0-9_-]{8,}\b|"
                          r"\b(?:sk|rk)_(?:test|live|proj|ant|service_account)_[a-z0-9_-]{8,}\b|"
                          r"\bsk-(?:proj|live|ant)-[a-z0-9_-]{8,}\b|"
                          r"\bgh[pousr]_[a-z0-9]{20,}\b|\bgithub_pat_[a-z0-9_]{20,}\b|\bAKIA[0-9A-Z]{16}\b|"
                          r"['\"]?\b[a-z0-9_]*(?:API_KEY|ACCESS_TOKEN|SECRET|PASSWORD|CREDENTIAL|BLOB_RW_TOKEN)[a-z0-9_]*['\"]?\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}", re.I)


def forbidden_key(value) -> str | None:
    """The first holdings-like field name in a nested value, or None. Values are never checked, only keys."""
    if isinstance(value, dict):
        for key, child in value.items():
            low = str(key).lower()
            if (word := next((w for w in FORBIDDEN if low.startswith(w)), None)) or (word := forbidden_key(child)):
                return word
    elif isinstance(value, (list, tuple)):
        for child in value:
            if word := forbidden_key(child):
                return word
    return None


def private_hits(value) -> list[str]:
    """Private text matches and redacted credential markers for publication errors."""
    texts = []

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                key = str(key)
                if isinstance(child, (str, int, float, bool)) or child is None:
                    texts.append(f"{key}: {child}")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            texts.append(item)

    visit(value)
    hits = []
    credentials = False
    for text in texts:
        hits.extend(m.group(0) for m in PRIVATE.finditer(text))
        credentials = credentials or bool(PEM_PRIVATE_KEY.search(text) or SECRET_VALUE.search(text))
        if len(hits) >= 5:
            hits = hits[:5]
    hits = list(dict.fromkeys(hits))[:5]
    if credentials:
        hits.append("credential material")
    return hits


def private_hits_file(path: str | Path) -> list[str]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".md":
        return private_hits(text)
    if path.suffix == ".json":
        try:
            return private_hits(json.loads(text))
        except ValueError:
            return private_hits(text)
    if path.suffix == ".jsonl":
        hits = []
        for line in text.split("\n"):
            if not line:
                continue
            try:
                hits.extend(private_hits(json.loads(line)))
            except ValueError:
                hits.extend(private_hits(line))
        return hits[:6]
    return private_hits(text)


class RankedError(ValueError):
    pass


@functools.lru_cache(maxsize=None)
def _validator(path: str):
    schema = json.loads(Path(path).read_text())
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    validate(data)
    return data


def validate(data: dict, ranking: bool = True) -> list[str]:
    """Raises RankedError on schema or tier-rule violations; returns spread warnings. `ranking=False` is a run's
    scores.json: every episode it scored, so the tier-3 rules for a published ranking do not apply."""
    try:
        _validator(str(SCHEMA_PATH)).validate(data)
    except jsonschema.ValidationError as exc:
        where = "/".join(map(str, exc.absolute_path)) or "root"
        raise RankedError(f"schema: {where}: {exc.message}") from None
    eps = data["episodes"]
    ranks = [e["rank"] for e in eps]
    if ranks != list(range(1, len(eps) + 1)):
        raise RankedError("ranks must run 1..n in order")
    if ranking:
        t3 = [e for e in eps if e["tier"] == 3]
        if len(t3) > 2:
            raise RankedError(f"tier 3 has {len(t3)} episodes; the cap is 2")
        if any(e["tier"] == 3 and e["rank"] <= 3 for e in eps):
            raise RankedError("tier 3 can never be a top pick (ranks 1-3)")
    if word := forbidden_key(data):
        raise RankedError(f"output must not contain holdings data ({word!r})")
    if hits := private_hits(data):
        raise RankedError(f"output must not contain private text: {hits}")
    warnings = []
    scores = sorted(e["score"] for e in eps)
    if len(scores) >= 5:
        if sum(s <= 4 for s in scores) < 0.3 * len(scores):
            warnings.append("spread: fewer than 30% of episodes score 4 or less")
        if max(scores) < 8:
            warnings.append("spread: no episode scores 8 or more")
        if len(set(scores)) <= 2:
            warnings.append("spread: scores are clustered")
    return warnings
