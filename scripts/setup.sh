#!/bin/sh
# Once per clone: make `git push` run the tests (.githooks/pre-push -> scripts/check.sh). Repo-local only (core.hooksPath in
# this clone's .git/config); never touches global git config. Also links data/ to the darkroom clone's wire/ folder
# ($DARKROOM, else the darkroom clone next to this one). Safe to run again.
set -eu
cd "$(dirname "$0")/.."
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git clone; nothing to set up" >&2; exit 1; }
chmod +x .githooks/* scripts/check.sh scripts/private-words.sh
git config --local core.hooksPath .githooks
echo "hooks installed: git push runs scripts/check.sh; commits refuse words listed in .private-words (core.hooksPath=.githooks, this clone only)"
[ -x .venv/bin/python ] || echo "note: no .venv yet; check.sh falls back to python3, which needs the dev extras (see README)" >&2

# data/ is a symlink into the private darkroom repo (docs/architecture.md). Keep an existing link or any folder with files in it.
dark="${DARKROOM:-$(cd .. && pwd)/darkroom}"
if [ -L data ]; then
  echo "data/ already links to $(readlink data)"
elif [ -d data ] && [ -n "$(ls -A data)" ]; then
  echo "note: data/ is a folder with files in it; left alone (move it, then run this again to link darkroom)" >&2
elif [ ! -d "$dark/wire" ]; then
  echo "note: no $dark/wire to link data/ to; clone d3ming/darkroom next to this clone or set DARKROOM, then run this again" >&2
else
  [ -d data ] && rmdir data  # an empty folder left by an earlier run
  ln -s "$dark/wire" data
  echo "data/ -> $dark/wire"
fi
