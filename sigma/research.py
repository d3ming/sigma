from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator

from .paths import data_root
from .ranked import private_hits

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "research-post.schema.json"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PRIVATE = re.compile(r"\b(?:system|developer|internal|private)\s+(?:prompt|instruction|strategy|notes?|workflow|data)\b|"
                     r"\b(?:blob[_ -]?read[_ -]?write[_ -]?token|api[_ -]?key|access[_ -]?token|client[_ -]?secret|secret[_ -]?key|bearer)\b|"
                     r"\b(?:account|customer|user)[_ -]?(?:number|id|balance)\b|\bpersonal email\b", re.I)
SECRET_VALUE = re.compile(r"\bvercel_blob_rw_[a-z0-9_-]{8,}\b|"
                          r"\b(?:sk|rk)_(?:test|live|proj|ant|service_account)_[a-z0-9_-]{8,}\b|"
                          r"\bsk-(?:proj|live|ant)-[a-z0-9_-]{8,}\b|"
                          r"\bgh[pousr]_[a-z0-9]{20,}\b|\bgithub_pat_[a-z0-9_]{20,}\b|\bAKIA[0-9A-Z]{16}\b|"
                          r"\b[a-z0-9_]*(?:API_KEY|ACCESS_TOKEN|SECRET|PASSWORD|CREDENTIAL|BLOB_RW_TOKEN)[a-z0-9_]*\s*[:=]\s*['\"]?[a-z0-9_./+=-]{8,}", re.I)
OWNERSHIP = re.compile(r"\b(?:i|we)\s+(?:own|hold|bought|sold|trimmed|added(?:\s+to)?|am\s+long|am\s+short)\b"
                       r"[^.!?]{0,100}\b(?:shares?|stock|position|portfolio|stake|[$]?[A-Z]{1,5}\b)|"
                       r"\b(?:my|our)\s+(?:shares?|stock|position|holdings?|allocation|cost basis)\b", re.I)
OUT_OF_SCOPE = re.compile(r"\bfair value\b|\b(?:buy|sell)\s+(?:recommendation|call)\b|"
                          r"\b(?:stock|market|investment)\s+(?:recommendation|call|thesis)\b|\bprice target\b", re.I)


def load(root: Path | None = None) -> list[dict]:
    """Load only explicitly allowlisted research posts; reject the build before output is replaced on any error."""
    root = Path(root or data_root()) / "research"
    allow_path = root / "index.json"
    try:
        allow = json.loads(allow_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(allow, dict) or set(allow) != {"posts"} or not isinstance(allow["posts"], list):
        raise ValueError("research/index.json must contain only a posts list")
    slugs = allow["posts"]
    if any(not isinstance(s, str) or not SLUG.fullmatch(s) for s in slugs):
        raise ValueError("research/index.json has an invalid or duplicate post slug")
    if len(slugs) != len(set(slugs)):
        raise ValueError("research/index.json has an invalid or duplicate post slug")
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    out = []
    for slug in slugs:
        p = root / "posts" / f"{slug}.json"
        item = json.loads(p.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(item), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"{p.name}: {errors[0].message}")
        text = " ".join(str(item[k]) for k in ("title", "summary", "body"))
        if PRIVATE.search(text) or SECRET_VALUE.search(text) or OWNERSHIP.search(text) or OUT_OF_SCOPE.search(text) or private_hits(text):
            raise ValueError(f"{p.name}: private or fund-related text is not publishable")
        date.fromisoformat(item["date"])
        out.append({"slug": slug, **item})
    return sorted(out, key=lambda x: (x["date"], x["slug"]), reverse=True)


def post_path(slug: str) -> str:
    return f"/research/{slug}/"
