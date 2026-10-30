"""`sigma verify`: does the live site serve what a run just published? Status and milliseconds go to the event log."""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urldefrag, urljoin

from . import events

REFRESH = re.compile(r'<meta http-equiv="refresh" content="\d+; *url=([^"]+)"', re.I)  # site.redirect_page's stand-in for a moved page


def get(url: str, timeout: float = 20) -> tuple[int, str, int, str]:
    """(HTTP status or 0, body, milliseconds, error text) for one GET; a network failure is status 0, not an exception."""
    t0, status, body, err = time.monotonic(), 0, "", ""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sigma-verify"}), timeout=timeout) as r:
            status, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    return status, body, round((time.monotonic() - t0) * 1000), err


def signals_problems(base: str, day: str, counts: dict) -> list[str]:
    """The Signals index of `day` and the list of days, as the live site serves them (sigma signals-index; schema/signals-index.schema.json)."""
    import json
    from pathlib import Path

    out = []
    for key, url in (("signals", f"{base}/signals/{day}.json"), ("signals_list", f"{base}/signals/index.json")):
        status, body, ms, err = get(url)
        counts |= {f"{key}_status": status, f"{key}_ms": ms}
        print(f"[verify] {url} {status or err} in {ms} ms")
        if status != 200:
            out.append(f"{url}: {err or f'HTTP {status}'}")
            continue
        try:
            doc = json.loads(body)
        except ValueError:
            out.append(f"{url}: not JSON")
            continue
        if key == "signals":
            from . import signals_index

            out += [f"{url}: {p}" for p in signals_index.check(doc, signals_index.PUBLISHED)]
            if doc.get("date") != day:
                out.append(f"{url}: the file is for {doc.get('date')}")
        elif day not in {d.get("date") for d in doc.get("days") or []}:
            out.append(f"{url}: does not list {day}")
    return out


def verify_cmd(args) -> None:
    """With --run: the home page and /runs/<run>/ must answer 200. When /runs/<run>/ is a redirect stand-in (a daily issue's
    address points at its day on the home page), the page it names must answer 200 and carry the #anchor it names. The
    --expect texts must be on the page that shows the issue: the stand-in's target, or /runs/<run>/ itself. This follows what
    the site serves, not what the run's name looks like, so it holds for any kind of run and any name. Without --run: the
    one url must answer 200 and hold every --expect text."""
    base = args.url.rstrip("/")
    problems, counts, seen = [], {}, {}

    def fetch(key: str, url: str) -> str | None:
        """The body of a 200, or None with the problem noted; each url is fetched once."""
        if url not in seen:
            seen[url] = get(url)
            status, _, ms, err = seen[url]
            counts.update({f"{key}_status": status, f"{key}_ms": ms})
            print(f"[verify] {url} {status or err} in {ms} ms")
            if status != 200:
                problems.append(f"{url}: {err or f'HTTP {status}'}")
        status, body, _, _ = seen[url]
        return body if status == 200 else None

    url = args.url
    if args.run:
        fetch("home", args.url)
        url = f"{base}/runs/{quote(args.run)}/"
        if (body := fetch("issue", url)) is not None and (m := REFRESH.search(body)):
            url, anchor = urldefrag(urljoin(url, html.unescape(m[1])))
            if (target := fetch("target", url)) is not None and anchor and f'id="{anchor}"' not in target:
                problems.append(f"{url}: has no #{anchor}, where /runs/{args.run}/ sends readers")
    if (body := fetch("page", url)) is not None:
        problems += [f"{url}: does not contain {text!r}" for text in args.expect if text not in body]
    if getattr(args, "signals", None):
        problems += signals_problems(base, args.signals, counts)
    events.note(**counts)
    if problems:
        sys.exit("\n".join(f"[verify] invalid: {p}" for p in problems))
