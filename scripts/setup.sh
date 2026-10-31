#!/bin/sh
set -eu
SIGMA=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$SIGMA"
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git clone" >&2; exit 1; }
chmod +x .githooks/* scripts/check.sh scripts/private-words.sh scripts/private_words.py
git config --local core.hooksPath .githooks
echo "hooks installed: git push runs scripts/check.sh; commits run the private-word check"
[ "${1:-}" = "--hooks-only" ] && exit 0
[ -x .venv/bin/python ] || echo "note: create .venv and install the dev extra before running scripts/check.sh" >&2
DATA_ROOT="${SIGMA_DATA_ROOT:-$SIGMA/data}"
mkdir -p "$DATA_ROOT"
if [ -z "${SIGMA_DATA_ROOT:-}" ] && [ ! -L "$DATA_ROOT" ] && [ -z "$(find "$DATA_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  cp -R "$SIGMA/examples/data/." "$DATA_ROOT/"
fi
echo "data root: $DATA_ROOT"
echo "Set SIGMA_DATA_ROOT to use a different private data directory."
