"""Local preview: build the site into .preview/dist, serve it on localhost, and rebuild when the code or published data changes.

    python3 scripts/preview_server.py [--port 8787]

Mirrors vercel.json's cleanUrls (/alpha/ and /sentiment both resolve). Only stdlib here; the build is `python -m wire.site`.
The Vercel function in api/ (site search) does not run locally. The server binds to 127.0.0.1 only."""
from __future__ import annotations

import argparse
import http.server
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".preview"
DIST = OUT / "dist"
WATCH = ["wire", "published", "site-assets", "web", "schema", "entities.json", "people.yaml", "creators.json", "show_links.yaml", "us-tickers.json", "x-accounts.json", "sources.yaml"]
LOCK = threading.Lock()


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def signature() -> tuple:
    n, newest = 0, 0.0
    for w in WATCH:
        p = ROOT / w
        files = [p] if p.is_file() else (f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc") if p.exists() else []
        for f in files:
            try:
                n += 1
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return n, newest


def build() -> bool:
    """Build into dist.new and swap it in, so a visitor never sees a half-written site and a failed build keeps the last good one."""
    new = OUT / "dist.new"
    shutil.rmtree(new, ignore_errors=True)
    OUT.mkdir(exist_ok=True)
    py = ROOT / ".venv" / "bin" / "python"
    t = time.time()
    r = subprocess.run([str(py if py.exists() else sys.executable), "-m", "wire.site", "--out", str(new), "--published", "published"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        log("BUILD FAILED, still serving the last good build:\n" + (r.stdout + r.stderr)[-1500:])
        return False
    with LOCK:
        old = OUT / "dist.old"
        shutil.rmtree(old, ignore_errors=True)
        if DIST.exists():
            DIST.rename(old)
        new.rename(DIST)
        shutil.rmtree(old, ignore_errors=True)
    log(f"built in {time.time() - t:.1f}s: {(r.stdout.strip().splitlines() or [''])[-1]}")
    return True


def watch(every: float) -> None:
    seen = signature()
    while True:
        time.sleep(every)
        now = signature()
        if now != seen:
            time.sleep(0.8)  # let a burst of saves settle
            seen = signature()
            log("change detected, rebuilding")
            build()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "wire-preview"

    def log_message(self, fmt, *a):
        log(f"{self.address_string()} {fmt % a}")

    def resolve(self) -> Path | None:
        rel = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
        base = (DIST / rel).resolve()
        if DIST.resolve() not in (base, *base.parents):
            return None
        for c in (base, base / "index.html", base.with_name(base.name + ".html") if rel and not rel.endswith("/") else base):
            if c.is_file():
                return c
        return None

    def do_GET(self, head: bool = False):
        with LOCK:
            f = self.resolve()
            code = 200
            if f is None:
                f, code = DIST / "404.html", 404
            try:
                data = f.read_bytes() if f.is_file() else b"not found\n"
            except OSError:
                data, code = b"not found\n", 404
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if f.suffix in (".md", ".txt", ".jsonl"):
            ctype = "text/plain" if f.suffix != ".md" else "text/markdown"
        if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET(head=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PREVIEW_PORT", "8787")))
    ap.add_argument("--poll", type=float, default=1.5)
    a = ap.parse_args()
    if not build() and not DIST.exists():
        sys.exit(1)
    threading.Thread(target=watch, args=(a.poll,), daemon=True).start()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    log(f"serving http://localhost:{a.port}/ from {DIST} (rebuilds on change)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
