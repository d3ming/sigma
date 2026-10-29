from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "ranked.schema.json"
FORBIDDEN = ("holding", "weight", "market_pct", "folio")
# Prose that only private material carries: our positions or allocation, money we moved, a local home path. Checked on
# every file that is published, not only on JSON keys (a holdings note pasted into a digest has no "holding" key).
PRIVATE = re.compile(
    r"\b(?:our|my|the owner'?s)\s+(?:portfolio|holdings?|positions?|allocations?|weights?|book)\b"
    r"|\bportfolio\s+(?:weights?|allocations?)\b|\bposition\s+sizes?\b|%\s+of\s+(?:our|my)\s+portfolio\b"
    r"|\bwe\s+(?:own|hold|bought|sold|trimmed|added\s+to)\s+(?:shares|\$?[A-Z]{1,5}\b)|\bcost\s+basis\b|\bunrealized\b"
    r"|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/", re.I)

PEM_PRIVATE_KEY = re.compile(r"-----BEGIN (?:(?:ENCRYPTED|RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----", re.I)
SECRET_VALUE = re.compile(r"\bvercel_blob_rw_[a-z0-9_-]{8,}\b|"
                          r"\b(?:sk|rk)_(?:test|live|proj|ant|service_account)_[a-z0-9_-]{8,}\b|"
                          r"\bsk-(?:proj|live|ant)-[a-z0-9_-]{8,}\b|"
                          r"\bgh[pousr]_[a-z0-9]{20,}\b|\bgithub_pat_[a-z0-9_]{20,}\b|\bAKIA[0-9A-Z]{16}\b|"
                          r"\b[a-z0-9_]*(?:API_KEY|ACCESS_TOKEN|SECRET|PASSWORD|CREDENTIAL|BLOB_RW_TOKEN)[a-z0-9_]*\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}", re.I)


def private_hits(text: str) -> list[str]:
    """Private text matches and redacted credential markers for publication errors."""
    hits = [m.group(0) for m in PRIVATE.finditer(text)][:5]
    if PEM_PRIVATE_KEY.search(text) or SECRET_VALUE.search(text):
        hits.append("credential material")
    return hits


class RankedError(ValueError):
    pass


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    validate(data)
    return data


def validate(data: dict, ranking: bool = True) -> list[str]:
    """Raises RankedError on schema or tier-rule violations; returns spread warnings. `ranking=False` is a run's
    scores.json: every episode it scored, so the tier-3 rules for a published ranking do not apply."""
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.validate(data, schema)
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
    blob = json.dumps(data).lower()
    for word in FORBIDDEN:
        if f'"{word}' in blob:
            raise RankedError(f"output must not contain holdings data ({word!r})")
    if hits := private_hits(json.dumps(data, ensure_ascii=False)):
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
