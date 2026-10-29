#!/bin/sh
# Run the test suite locally, for when GitHub Actions is unavailable (billing, outage). Same suite as
# .github/workflows/tests.yml. CI=1 selects the slow-machine time limits in conftest.py.
#   scripts/check.sh           run the suite
#   scripts/check.sh --hook    same as scripts/setup.sh: run it before every `git push` from this clone
set -eu
cd "$(dirname "$0")/.."
[ "${1:-}" = "--hook" ] && exec scripts/setup.sh  # old name for scripts/setup.sh
py=python3
main="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"  # a worktree has no .venv of its own: use the main checkout's
for v in .venv "$main/.venv"; do [ -x "$v/bin/python" ] && { py="$v/bin/python"; break; }; done
scripts/private-words.sh
# PYTHONPATH=. tests this checkout's code, not the main checkout's editable install
CI=1 PYTHONPATH=. exec "$py" -m pytest -q
