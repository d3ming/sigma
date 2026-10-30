#!/bin/sh
# Refuse private words (the maintainer's name, say) in tracked files or a commit message. The list is .private-words at the
# repo root: git-ignored, one case-insensitive whole word or phrase per line, so the list itself never enters the repo.
# No list, no check. LICENSE is skipped: a copyright line needs a legal name.
#   scripts/private-words.sh            every tracked file
#   scripts/private-words.sh --msg F    a commit message file (the commit-msg hook)
set -eu
cd "$(dirname "$0")/.."
list=.private-words
[ -s "$list" ] || exit 0
pat=$(grep -v '^[[:space:]]*$' "$list" | sed 's/[][\.*^$/]/\\&/g' | paste -sd'|' -)
if [ "${1:-}" = "--msg" ]; then
  if grep -v '^#' "$2" | grep -inwE "$pat" >&2; then echo "commit message names something in $list; reword it" >&2; exit 1; fi
  exit 0
fi
if git grep --cached -inwE "$pat" -- . ':!LICENSE' >&2; then echo "staged files name something in $list; reword them (see AGENTS.md)" >&2; exit 1; fi
