from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import data_root

DEFAULT_SITE = "Sigma"
DEFAULT_BASE_URL = "https://example.invalid"


@dataclass(frozen=True)
class SiteIdentity:
    name: str = DEFAULT_SITE
    base_url: str = DEFAULT_BASE_URL
    maker: str = ""
    x_profile: str = ""
    search_api_url: str = "/api/search"


def load(path: Path | None = None) -> SiteIdentity:
    config_path = Path(path) if path else Path(os.environ.get("SIGMA_SITE_CONFIG") or data_root() / "site.json")
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        values = {}
    if not isinstance(values, dict) or set(values) - {"site_name", "base_url", "maker", "x_profile", "search_api_url"}:
        raise ValueError(f"invalid site identity config: {config_path}")
    base_url = str(os.environ.get("SIGMA_BASE_URL") or values.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    if not base_url.startswith(("https://", "http://localhost")):
        raise ValueError("site base_url must use HTTPS or localhost")
    search_api_url = str(values.get("search_api_url") or "/api/search")
    if not re.fullmatch(r"/(?!/)[A-Za-z0-9/_-]*", search_api_url):
        raise ValueError("site search_api_url must be a same-origin path")
    x_profile = str(values.get("x_profile") or "")
    if x_profile and not x_profile.startswith("https://"):
        raise ValueError("site x_profile must use HTTPS")
    return SiteIdentity(
        name=str(values.get("site_name") or DEFAULT_SITE), base_url=base_url,
        maker=str(values.get("maker") or ""), x_profile=x_profile,
        search_api_url=search_api_url,
    )


if __name__ == "__main__":
    print(load().base_url)
