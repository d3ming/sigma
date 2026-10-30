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
git pull -q --rebase --autostash
git diff --cached --quiet || { echo "[data] refusing to save because the pull left staged files" >&2; exit 1; }
git add -- "$REL" ':(exclude,glob)**/.env*' ':(exclude,glob)**/.private-words'
if git diff --cached --quiet; then
  echo "[data] nothing to commit"
  exit 0
fi
STAGED=$(git diff --cached --name-only)
while IFS= read -r staged_path; do
  if [[ "$REL" != . && "$staged_path" != "$REL"/* ]]; then
    echo "[data] refusing to commit a staged path outside the configured data root" >&2
    exit 1
  fi
  case "$staged_path" in
    .env*|*/.env*|.private-words|*/.private-words)
      echo "[data] refusing to commit a credential or private-word file" >&2
      exit 1
      ;;
  esac
done <<< "$STAGED"
git commit -q -m "$MSG"
COMMITTED=$(git diff-tree --no-commit-id --name-only -r HEAD)
while IFS= read -r staged_path; do
  if [[ "$REL" != . && "$staged_path" != "$REL"/* ]]; then
    echo "[data] refusing to push a commit outside the configured data root" >&2
    exit 1
  fi
  case "$staged_path" in
    .env*|*/.env*|.private-words|*/.private-words)
      echo "[data] refusing to push a credential or private-word file" >&2
      exit 1
      ;;
  esac
done <<< "$COMMITTED"
git push -q
echo "[data] pushed: $(git log --oneline -1)"
