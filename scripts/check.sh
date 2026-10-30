#!/bin/sh
#   scripts/check.sh           the private-word guard, the agent-doc check and the full suite
#   scripts/check.sh --tests   the suite alone
#   scripts/check.sh --fast    the suite without the `slow` tests, stopping at the first failure
#   scripts/check.sh --hook    same as scripts/setup.sh: run it before every `git push` from this clone
set -eu
cd "$(dirname "$0")/.."
[ "${1:-}" = "--hook" ] && exec scripts/setup.sh  # old name for scripts/setup.sh
py=python3
main="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"  # a worktree has no .venv of its own: use the main checkout's
for v in .venv "$main/.venv"; do [ -x "$v/bin/python" ] && { py="$v/bin/python"; break; }; done
tests=
if [ "${1:-}" = "--tests" ]; then tests=1; shift; fi
if [ "${1:-}" = "--fast" ]; then tests=1; shift; set -- -x -m "not slow" "$@"; fi
if [ -z "$tests" ]; then
  scripts/private-words.sh
  "$py" scripts/check_agent_docs.py
fi
# PYTHONPATH=. tests this checkout's code, not the main checkout's editable install
PYTHONPATH=. exec "$py" -m pytest -q "$@"
