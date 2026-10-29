#!/bin/zsh
# Commit Wire's private data to the darkroom repo: data/ is a symlink into darkroom/wire/. Run after the decision-log step.
# First refreshes the private call ledger (`wire calls`, summary line only; a failure is printed and ignored). The daily, weekly
# and X-edition runs all end here after their stances are merged, so each night's ledger is saved with the run. It then refreshes the
# site's search index the same way (`wire library ingest --all`, then `wire search-index --upload`).
# Copies run JSON and Markdown, transcripts included, into wire/runs-private/ (they are never published), stages only wire/ (minus wire/x/scan/, the scanner's, and wire/prices/, a cache), pulls with rebase first (darkroom has
# other writers), commits and pushes. Exits 0 with nothing to commit.
set -euo pipefail
WIRE="${0:A:h:h:h}"
DARK="${DARKROOM:-$HOME/projects/darkroom}"
MSG="${1:-wire: $(date +%Y-%m-%d) run}"

# One `darkroom` line in data/events/ whatever happens (archived and committed by the next run). `wire event` always exits 0.
STATE=failed STAGE=start CALLS_FAIL=""
log_event() {
  local s=ok pushed=0 more=()
  [[ $STATE == failed ]] && s=fail
  [[ $STATE == pushed ]] && pushed=1
  [[ $s == ok && -n $CALLS_FAIL ]] && s=warn
  [[ -n $CALLS_FAIL ]] && more+=(--warn "$CALLS_FAIL")
  [[ $s == fail ]] && more+=(--err "failed at $STAGE")
  "$WIRE/.venv/bin/wire" event darkroom --status $s --dur $SECONDS --n pushed=$pushed "${more[@]}" >/dev/null 2>&1 || true
}
trap log_event EXIT

[[ -d "$DARK/.git" ]] || { echo "[darkroom] no repo at $DARK"; exit 1; }
cd "$DARK"
STAGE=pull
git pull -q --rebase --autostash
# Closing prices are cached 12 hours, so the second run of a night fetches nothing.
if out=$(cd "$WIRE" && .venv/bin/wire calls 2>&1); then echo "${out##*$'\n'}"; else CALLS_FAIL="[calls] failed, ignored: ${out##*$'\n'}"; echo "$CALLS_FAIL"; fi
# The site's search: reload the library from every run, then copy its transcript index to the private wire-search store (needs
# SEARCH_READ_WRITE_TOKEN in the environment or in the repo's git-ignored .env.local). Each step prints one line; a failure is ignored.
if out=$(cd "$WIRE" && .venv/bin/wire library ingest --all 2>&1); then echo "${out##*$'\n'}"; else echo "[library] ingest failed, ignored: ${out##*$'\n'}"; fi
if out=$(cd "$WIRE" && .venv/bin/wire search-index --upload 2>&1); then echo "${out##*$'\n'}"; else echo "[search-index] failed, ignored: ${out##*$'\n'}"; fi
STAGE=stage
rsync -a --prune-empty-dirs --include='*/' --include='*.json' --include='*.md' --exclude='*' "$WIRE/runs/" "$DARK/wire/runs-private/"
# The live event log, wire/events/, is git-ignored in darkroom: it is appended to all day, and a tracked file that is always dirty is
# what `git pull --autostash` parks in a stash it may not restore. Archive it into a tracked folder; nothing else writes the archive.
[[ -d "$DARK/wire/events" ]] && rsync -a "$DARK/wire/events/" "$DARK/wire/events-archive/"
git add -- wire/ ":(exclude)wire/x/scan"  # the scanner owns wire/x/scan/ and commits it itself; wire/prices/ is a cache, ignored by darkroom's .gitignore (naming an ignored path here makes git add exit 1)
if git diff --cached --quiet; then
  echo "[darkroom] nothing to commit"
  STATE=nothing
  exit 0
fi
STAGE=commit
git commit -q -m "$MSG"
STAGE=push
git push -q
STATE=pushed
echo "[darkroom] pushed: $(git log --oneline -1)"
