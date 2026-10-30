#!/bin/sh
# Refuse private words in tracked files or a commit message. Thin wrapper over scripts/private_words.py, which holds the
# salted-hash list (.private-words.sha256) and fails closed when it is missing. Used by the git hooks and scripts/check.sh.
set -eu
cd "$(dirname "$0")/.."
command -v python3 >/dev/null 2>&1 || { echo "python3 is required for the private-word guard" >&2; exit 1; }
exec python3 scripts/private_words.py "$@"
