#!/bin/zsh
set -euo pipefail
SIGMA="${0:A:h:h:h}"
DATA="${SIGMA_DATA_ROOT:-$SIGMA/data}"
MSG="${1:-sigma: $(date +%Y-%m-%d) data}"

[[ -d "$DATA" ]] || { echo "[data] no directory at $DATA; set SIGMA_DATA_ROOT" >&2; exit 1; }
DATA=$(cd "$DATA" && pwd -P)
REPO=$(git -C "$DATA" rev-parse --show-toplevel 2>/dev/null) || { echo "[data] $DATA is not inside a Git repository" >&2; exit 1; }
REPO=$(cd "$REPO" && pwd -P)
[[ "$REPO" != "$SIGMA" ]] || { echo "[data] refusing to stage anything from the public Sigma repository" >&2; exit 1; }
common_dir() {
  local root=$1 common
  common=$(git -C "$root" rev-parse --git-common-dir) || return 1
  [[ "$common" == /* ]] || common="$root/$common"
  (cd "$common" && pwd -P)
}
SIGMA_COMMON=$(common_dir "$SIGMA") || { echo "[data] could not identify the Sigma Git repository" >&2; exit 1; }
DATA_COMMON=$(common_dir "$REPO") || { echo "[data] could not identify the data Git repository" >&2; exit 1; }
[[ "$SIGMA_COMMON" != "$DATA_COMMON" ]] || { echo "[data] refusing to stage data from a linked checkout of the public Sigma repository" >&2; exit 1; }
case "$DATA" in
  "$REPO") REL=.;;
  "$REPO"/*) REL=${DATA#"$REPO"/};;
  *) echo "[data] data root must be inside its Git repository" >&2; exit 1;;
esac

cd "$REPO"
git diff --cached --quiet || { echo "[data] refusing to save with pre-existing staged files" >&2; exit 1; }
git remote get-url origin >/dev/null 2>&1 || { echo "[data] private data checkout needs an origin remote" >&2; exit 1; }
git fetch -q origin main || { echo "[data] could not fetch private origin/main" >&2; exit 1; }
MAIN=$(git rev-parse --verify refs/remotes/origin/main^{commit}) || { echo "[data] private origin/main is missing" >&2; exit 1; }
BASE=$(git merge-base HEAD "$MAIN") || { echo "[data] source branch and private main have no common history" >&2; exit 1; }

INDEX=$(mktemp "${TMPDIR:-/tmp}/sigma-data-index.XXXXXX")
PATCH=$(mktemp "${TMPDIR:-/tmp}/sigma-data-patch.XXXXXX")
WORK=""
BRANCH=""
cleanup() {
  if [[ -n "$WORK" && -d "$WORK" ]]; then git worktree remove --force "$WORK" >/dev/null 2>&1 || true; fi
  if [[ -n "$BRANCH" ]]; then git branch -D "$BRANCH" >/dev/null 2>&1 || true; fi
  [[ -z "$INDEX" || ! -e "$INDEX" ]] || command rm -f "$INDEX"
  [[ -z "$PATCH" || ! -e "$PATCH" ]] || command rm -f "$PATCH"
}
trap cleanup EXIT
command rm -f "$INDEX"
tgit() { local -x GIT_INDEX_FILE="$INDEX"; command git "$@"; }
tgit read-tree "$BASE"
tgit add -A -- "$REL"
while IFS= read -r -d '' owned_path; do
  base="${owned_path:t}"
  lower="${owned_path:l}"
  if [[ "$base" == .env* || "$base" == .private-words || "$lower" == *secret* || "$lower" == *credential* ||
        "$lower" == *.sqlite || "$lower" == *.sqlite-* || "$lower" == *.sqlite3 || "$lower" == *.sqlite3-* || "$lower" == *.db || "$lower" == *.db-* || "$lower" == *.pem || "$lower" == *.key || "$lower" == *.p12 ||
        "$lower" == *feedcache* || "$lower" == *feed-cache* || "$lower" == *feed_cache* || "$lower" == */.cache/* || "$lower" == */cache/* || "$lower" == */caches/* ||
        "$lower" == *transcript* || (("$lower" == runs/* || "$lower" == */runs/*) && "$lower" == *.md) ]]; then
    tgit reset -q "$BASE" -- "$owned_path" 2>/dev/null || true
  fi
done < <(tgit diff --cached --name-only -z "$BASE" -- "$REL")
SNAPSHOT=$(tgit write-tree)
DELETED=$(git diff --name-only --diff-filter=D "$BASE" "$SNAPSHOT" -- "$REL")
[[ -z "$DELETED" ]] || { echo "[data] refusing to delete private data without a saved copy" >&2; exit 1; }
git -c core.quotepath=false diff --binary --full-index "$BASE" "$SNAPSHOT" -- "$REL" > "$PATCH"

if [[ ! -s "$PATCH" ]]; then
  echo "[data] private main already has the current owned data"
  echo "[data] main: $MAIN"
  echo "[data] owned tree: $(git rev-parse "$MAIN:$REL")"
  exit 0
fi

BRANCH="sigma-data-$(date +%Y%m%d-%H%M%S)-$$"
WORK="${TMPDIR:-/tmp}/$BRANCH"
git worktree add -q -b "$BRANCH" "$WORK" "$MAIN"
if ! git -C "$WORK" apply --3way --index "$PATCH"; then
  echo "[data] owned data conflicts with private main; source checkout was left unchanged" >&2
  exit 1
fi
while IFS= read -r -d '' owned_path; do
  case "$REL" in
    .) ;;
    *) [[ "$owned_path" == "$REL"/* ]] || { echo "[data] refusing a change outside the configured data root" >&2; exit 1; };;
  esac
done < <(git -C "$WORK" diff --cached --name-only -z)
git -C "$WORK" diff --cached --quiet && {
  echo "[data] private main already has the current owned data"
  echo "[data] main: $MAIN"
  echo "[data] owned tree: $(git -C "$WORK" rev-parse "HEAD:$REL")"
  exit 0
}
git -C "$WORK" commit -q -m "$MSG"
git -C "$WORK" push -q origin HEAD:refs/heads/main || { echo "[data] private main advanced; no data was force-pushed" >&2; exit 1; }
MAIN=$(git -C "$WORK" rev-parse HEAD)
echo "[data] main: $MAIN"
echo "[data] owned tree: $(git -C "$WORK" rev-parse "HEAD:$REL")"
