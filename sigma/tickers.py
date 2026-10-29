"""The list of valid US tickers: `us-tickers.json`, {ticker: company name}, reduced from the SEC's
company_tickers_exchange.json to the symbols listed on NYSE, Nasdaq, NYSE American or Cboe.

The stance labels and the board count only these. A foreign line (005930.KS), an OTC name, an index or a made-up
symbol never scores; an exchange-listed fund (SPY) does. The list is vendored and committed; `sigma tickers-refresh` rebuilds it. Standard library only,
because the site host builds with nothing else.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "us-tickers.json"
SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
EXCHANGES = {"Nasdaq", "NYSE", "NYSE American", "CBOE"}  # the SEC file's own spellings
# Broad index funds: their stance also counts toward the Market line (board.py). The SEC file lists only some of them
# (SPY, DIA), so load() adds the rest; a refresh of the file never drops them.
BROAD_FUNDS = {"SPY": "SPDR S&P 500 ETF Trust", "QQQ": "Invesco QQQ Trust", "IWM": "iShares Russell 2000 ETF",
               "DIA": "SPDR Dow Jones Industrial Average ETF Trust", "VOO": "Vanguard S&P 500 ETF",
               "VTI": "Vanguard Total Stock Market ETF", "RSP": "Invesco S&P 500 Equal Weight ETF"}


def normalize(sym) -> str:
    """The SEC's spelling of a symbol: upper case, no $, share classes with a dash (BRK.B -> BRK-B)."""
    return str(sym or "").strip().lstrip("$").upper().replace(".", "-").replace("/", "-")


def load(path: Path | None = None) -> dict[str, str]:
    try:
        data = json.loads((path or FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {**BROAD_FUNDS, **data} if isinstance(data, dict) and data else {}


def valid(sym, us: dict) -> str:
    """The listed spelling of `sym`, or "" when it is not a US-listed ticker. "private:..." never is."""
    s = normalize(sym)
    return s if s in us and not str(sym).startswith("private:") else ""


def reduce(raw: dict) -> dict[str, str]:
    """SEC's {"fields": [...], "data": [[...], ...]} -> {ticker: name} for the listed exchanges, sorted by ticker."""
    fields = raw["fields"]
    t, n, x = fields.index("ticker"), fields.index("name"), fields.index("exchange")
    out: dict[str, str] = {}
    for row in raw["data"]:
        if row[x] in EXCHANGES and row[t] and row[n]:
            out.setdefault(normalize(row[t]), str(row[n]).strip())
    return dict(sorted(out.items()))


def refresh_cmd(args) -> None:
    """Fetch the SEC file and write us-tickers.json. The SEC refuses a User-Agent without a contact address, so the
    operator gives one (--contact or SIGMA_SEC_CONTACT): the address stays out of the public repo."""
    import sys

    contact = args.contact or os.environ.get("SIGMA_SEC_CONTACT")
    if not contact:
        sys.exit("[tickers] the SEC needs a contact in the User-Agent: pass --contact you@example.com or set SIGMA_SEC_CONTACT")
    req = urllib.request.Request(SEC_URL, headers={"User-Agent": f"Sigma {contact}", "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = json.loads(r.read())
    except (OSError, ValueError) as exc:
        sys.exit(f"[tickers] could not fetch {SEC_URL}: {exc}")
    out = reduce(raw)
    old = load(Path(args.out))
    Path(args.out).write_text(json.dumps(out, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[tickers] {args.out}: {len(out)} tickers ({len(set(out) - set(old)):+} new, {len(set(old) - set(out))} gone)")
