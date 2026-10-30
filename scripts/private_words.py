#!/usr/bin/env python3
"""Refuse private words (a maintainer's name or handle, say) in tracked files, commit messages and PR text.

The list is `.private-words.sha256`, committed: a salt, then one salted SHA-256 per lower-cased word or phrase, so the
list itself never spells a word out. A word is matched whole and case-insensitively; a phrase is up to four words.
Hashing hides the words from a casual reader. It does not stop someone who guesses them, so a hash list is a guard
against accidents, not a secret.

  scripts/private_words.py                 every tracked file, as staged (the pre-commit hook, CI)
  scripts/private_words.py --msg FILE      one commit message (the commit-msg hook)
  scripts/private_words.py --log RANGE     every commit message in a git range (CI)
  scripts/private_words.py --env NAME ...  the text in environment variables, e.g. a PR title (CI)
  scripts/private_words.py --add           read words from stdin, one per line, and add their hashes to the list

A missing or empty list fails, never passes. An optional git-ignored `.private-words` (one plain word per line) adds to
the committed list on one machine. A hit prints file:line and never the word.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / ".private-words.sha256"
LOCAL = ROOT / ".private-words"
MAX_WORDS = 4  # the longest phrase the list can hold
TOKEN = re.compile(r"[a-z0-9_]+")


def normalize(phrase: str) -> str:
    return " ".join(TOKEN.findall(phrase.lower()))


def digest(salt: str, phrase: str) -> str:
    return hashlib.sha256(f"{salt}:{normalize(phrase)}".encode()).hexdigest()


def load(path: Path = LIST, local: Path | None = LOCAL) -> tuple[str, set[str]]:
    """The salt and the set of hashes. Raises SystemExit if the committed list is missing or empty."""
    if not path.is_file():
        sys.exit(f"{path.name} is missing: the private-word guard fails closed. Restore it from the repository.")
    salt, hashes = "", set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("salt "):
            salt = line.split(None, 1)[1]
        elif re.fullmatch(r"[0-9a-f]{64}", line):
            hashes.add(line)
    if not salt or not hashes:
        sys.exit(f"{path.name} has no salt or no hashes: the private-word guard fails closed.")
    if local is not None and local.is_file():
        for line in local.read_text().splitlines():
            if normalize(line):
                hashes.add(digest(salt, line))
    return salt, hashes


def hits_in_line(line: str, salt: str, hashes: set[str]) -> bool:
    tokens = TOKEN.findall(line.lower())
    for i in range(len(tokens)):
        for n in range(1, MAX_WORDS + 1):
            if i + n <= len(tokens) and digest(salt, " ".join(tokens[i:i + n])) in hashes:
                return True
    return False


def scan_text(text: str, name: str, salt: str, hashes: set[str]) -> list[str]:
    return [f"{name}:{no}" for no, line in enumerate(text.splitlines(), 1) if hits_in_line(line, salt, hashes)]


def staged_files() -> list[tuple[str, str]]:
    """(path, text) for every tracked file as staged; binary files are skipped."""
    paths = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    paths = [p.decode() for p in paths if p]
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, check=True, capture_output=True,
                          input="".join(f":{p}\n" for p in paths).encode())
    out, pos, files = proc.stdout, 0, []
    for p in paths:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        if len(header) != 3:  # "<name> missing": a path git lists but cannot read
            pos = end + 1
            continue
        size = int(header[2])
        body = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
        if b"\0" not in body[:8000]:
            files.append((p, body.decode("utf-8", "replace")))
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--msg", metavar="FILE")
    g.add_argument("--log", metavar="RANGE")
    g.add_argument("--env", nargs="+", metavar="NAME")
    g.add_argument("--add", action="store_true")
    a = ap.parse_args(argv)
    if a.add:
        salt = ""
        old = LIST.read_text().splitlines() if LIST.is_file() else []
        for line in old:
            if line.startswith("salt "):
                salt = line.split(None, 1)[1]
        salt = salt or os.urandom(16).hex()
        hashes = {line.strip() for line in old if re.fullmatch(r"[0-9a-f]{64}", line.strip())}
        hashes |= {digest(salt, w) for w in sys.stdin.read().splitlines() if normalize(w)}
        header = [ln for ln in old if ln.startswith("#")] or ["# Salted SHA-256 of private words; see scripts/private_words.py."]
        LIST.write_text("\n".join(header + [f"salt {salt}"] + sorted(hashes)) + "\n")
        print(f"{LIST.name}: {len(hashes)} hashes")
        return 0
    salt, hashes = load()
    found: list[str] = []
    what = "staged files"
    if a.msg:
        what = "the commit message"
        text = "".join(ln for ln in Path(a.msg).read_text().splitlines(True) if not ln.startswith("#"))
        found = scan_text(text, "message", salt, hashes)
    elif a.log:
        what = "a commit message in the range"
        log = subprocess.run(["git", "log", "--format=%B%x00", a.log], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        for i, msg in enumerate(m for m in log.split("\0") if m.strip()):
            found += scan_text(msg, f"commit-{i + 1}", salt, hashes)
    elif a.env:
        what = "the text in " + ", ".join(a.env)
        for name in a.env:
            found += scan_text(os.environ.get(name, ""), name, salt, hashes)
    else:
        for path, text in staged_files():
            if hits_in_line(path, salt, hashes):
                found.append(f"{path} (the file name)")
            found += scan_text(text, path, salt, hashes)
    if found:
        print("\n".join(found[:50]), file=sys.stderr)
        print(f"{what} name a private word from {LIST.name}; reword (see AGENTS.md). File:line shown, never the word.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
