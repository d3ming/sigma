#!/bin/zsh
set -euo pipefail
CALLER_PWD=$PWD
SIGMA="${0:A:h:h:h}"
cd "$SIGMA"
DATA_ROOT="${SIGMA_DATA_ROOT:-$SIGMA/data}"
[[ $DATA_ROOT == /* ]] || DATA_ROOT="$CALLER_PWD/$DATA_ROOT"
export SIGMA_DATA_ROOT="$DATA_ROOT"
PYTHON=${SIGMA_PYTHON:-}
if [[ -z $PYTHON ]]; then
  COMMON_DIR=$(git -C "$SIGMA" rev-parse --git-common-dir)
  [[ $COMMON_DIR == /* ]] || COMMON_DIR="$SIGMA/$COMMON_DIR"
  MAIN_CHECKOUT=$(cd "$COMMON_DIR/.." && pwd)
  if [[ -x "$SIGMA/.venv/bin/python" ]]; then PYTHON="$SIGMA/.venv/bin/python"; elif [[ -x "$MAIN_CHECKOUT/.venv/bin/python" ]]; then PYTHON="$MAIN_CHECKOUT/.venv/bin/python"; else PYTHON=python3; fi
fi
STATE="${SIGMA_DEPLOY_STATE_DIR:-$SIGMA/.vercel}"
ARTIFACTS="${SIGMA_DEPLOY_ARTIFACT_DIR:-$SIGMA/.vercel}"
LOG="$STATE/deploys"
STAMP="$STATE/deployed-hash"
FAILLOG="$STATE/deploy-failed.log"
BUILD_OUT="$STATE/build.out"
BUILD_ERR="$STATE/build.err"

audit_publication() {
  "$PYTHON" - "$1" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
private_parts = {
    "data", ".local", "published", "followlists", "followlist", "docs-migration",
    "sources.yaml", "people.yaml", "creators.json", "x-accounts.json", "entities.json", "show_links.yaml",
}
private_files = {".private-words", "PLAN.md", "followlists.json", "followlists.yaml", "followlists.txt"}
for path in root.rglob("*"):
    parts = path.relative_to(root).parts
    if any(part.startswith(".env") or part.startswith("followlist") or part in private_parts or part in private_files for part in parts):
        sys.exit(1)
    if any(parts[index:index + 2] == ("docs", "migration") for index in range(len(parts) - 1)):
        sys.exit(1)
PY
}

TODAY=$(TZ=America/Los_Angeles date +%F)
MAX=${SIGMA_DEPLOYS_PER_DAY:-2}
USED=$(grep -c "^$TODAY " "$LOG" 2>/dev/null || true); USED=${USED:-0}
MODE=${1:-}
if [[ $MODE == --help || $MODE == -h ]]; then
  cat <<'HELP'
usage: site-deploy.sh [--site-only|--preflight [SOURCE_SHA]|--dry-run|--deploy-staged HASH PLAN_ID]

Builds a production Vercel output, hashes the generated publication content,
and deploys the frozen prebuilt output when its content changed. --preflight
builds and checks quota without upload; --dry-run builds without quota refusal.
--site-only runs the static site builder without Vercel or an account. Production
upload requires local main to match origin/main and an annotated version tag
for the current main commit. --deploy-staged requires its exact prepared plan ID and uploads the frozen artifact
identified by its full content hash, without rebuilding it.
HELP
  exit 0
fi
[[ $MODE == --site-only || $MODE == --dry-run || $MODE == --preflight || $MODE == --deploy-staged ]] || { echo "usage: site-deploy.sh [--site-only|--preflight [SOURCE_SHA]|--dry-run|--deploy-staged HASH PLAN_ID]" >&2; exit 2; }
[[ $# -le 1 || ( $MODE == --preflight && $# -eq 2 ) || ( $MODE == --deploy-staged && $# -eq 3 ) ]] || { echo "usage: site-deploy.sh [--site-only|--preflight [SOURCE_SHA]|--dry-run|--deploy-staged HASH PLAN_ID]" >&2; exit 2; }
SOURCE_SHA=HEAD
if [[ $MODE == --preflight && $# -eq 2 ]]; then
  SOURCE_SHA=$(git rev-parse "$2^{commit}") || { echo "[site] refused: preflight source commit does not exist" >&2; exit 1; }
fi
if [[ $MODE == --preflight ]]; then echo "[site] source commit: $(git -C "$SIGMA" rev-parse "$SOURCE_SHA")"; fi
if [[ $MODE == --deploy-staged ]]; then
  BRANCH=$(git branch --show-current)
  if [[ $BRANCH != main ]]; then
    echo "[site] refused: production deploys only from main, and this clone is on '${BRANCH:-detached HEAD}'." >&2
    exit 1
  fi
  git fetch -q origin main
  HEAD_SHA=$(git rev-parse HEAD)
  [[ $HEAD_SHA == $(git rev-parse origin/main) ]] || { echo "[site] refused: local main is not at origin/main" >&2; exit 1; }
  if [[ $MODE == --deploy-staged ]]; then
    VERSION=$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "$SIGMA/pyproject.toml" | head -1)
    [[ -n $VERSION ]] || { echo "[site] refused: cannot read version tag from pyproject.toml" >&2; exit 1; }
    TAG="v$VERSION"
    TAG_REFS=$(git ls-remote origin "refs/tags/$TAG" "refs/tags/$TAG^{}")
    TAG_OBJECT=$(printf '%s\n' "$TAG_REFS" | awk -v ref="refs/tags/$TAG" '$2 == ref { print $1 }')
    TAG_COMMIT=$(printf '%s\n' "$TAG_REFS" | awk -v ref="refs/tags/$TAG^{}" '$2 == ref { print $1 }')
    [[ -n $TAG_OBJECT && -n $TAG_COMMIT && $TAG_OBJECT != "$TAG_COMMIT" && $TAG_COMMIT == "$HEAD_SHA" ]] \
      || { echo "[site] refused: remote annotated version tag $TAG does not identify current main" >&2; exit 1; }
  fi
fi
BUILD_OUT="$SIGMA/.vercel/build.out"
BUILD_ERR="$SIGMA/.vercel/build.err"
BASE_URL=${SIGMA_BASE_URL:-}
if [[ $MODE == --site-only && -z $BASE_URL ]]; then
  BASE_URL=$(SIGMA_DATA_ROOT="$DATA_ROOT" PYTHONPATH="$SIGMA" "$PYTHON" -m sigma.site_config) || { echo "[site] could not resolve the configured base URL" >&2; exit 1; }
fi
if [[ $MODE == --site-only ]]; then
  PYTHONPATH="$SIGMA" SIGMA_BASE_URL="$BASE_URL" "$PYTHON" - "$SIGMA" <<'PY'
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile

repo = pathlib.Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix="sigma-site-only-") as temp:
    output = pathlib.Path(temp) / "site"
    subprocess.run([sys.executable, "-m", "sigma.site", "--out", str(output)], cwd=repo, env=os.environ.copy(), check=True)
    digest = hashlib.sha256()
    files = sorted(path for path in output.rglob("*") if path.is_file())
    for path in files:
        name = path.relative_to(output).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    print(f"[site] local content: {digest.hexdigest()[:12]} ({len(files)} files); no Vercel account or upload used")
PY
  exit $?
fi
mkdir -p "$SIGMA/.vercel" "$STATE" "$ARTIFACTS"
if [[ $MODE == --deploy-staged ]]; then
  HASH=$2
  PLAN_ID=$3
  [[ $HASH =~ '^[0-9a-f]{64}$' ]] || { echo "[site] refused: invalid publication hash" >&2; exit 2; }
  [[ $PLAN_ID =~ '^[0-9a-f]{64}$' ]] || { echo "[site] refused: an exact prepared plan ID is required" >&2; exit 2; }
  PLAN_DIR=${SIGMA_RELEASE_PLAN_DIR:-$STATE/release-plans}
  "$PYTHON" - "$PLAN_DIR/$PLAN_ID.json" "$PLAN_DIR/$PLAN_ID.md" "$PLAN_DIR/$PLAN_ID.manifest.json" "$PLAN_ID" "$HASH" "$HEAD_SHA" "$TAG" "$SIGMA/.vercel/project.json" <<'PY'
import hashlib
import json
import pathlib
import sys

plan_path, notes_path, manifest_path = map(pathlib.Path, sys.argv[1:4])
plan_id, artifact_hash, source_sha, tag = sys.argv[4:8]
project_path = pathlib.Path(sys.argv[8])
try:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    notes = notes_path.read_text(encoding="utf-8")
    manifest = manifest_path.read_bytes()
    project_hash = hashlib.sha256(project_path.read_bytes()).hexdigest()
except (OSError, ValueError):
    raise SystemExit("[site] refused: prepared publication plan or linked project is missing")
payload = {key: value for key, value in plan.items() if key != "plan_id"}
expected_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
if plan.get("plan_id") != str(plan_id) or expected_id != str(plan_id):
    raise SystemExit("[site] refused: prepared publication plan does not match its ID")
if plan.get("artifact_hash") != artifact_hash or plan.get("source_sha") != source_sha or plan.get("tag") != tag:
    raise SystemExit("[site] refused: prepared plan does not authorize this source and artifact")
if plan.get("target") != "production" or plan.get("project_hash") != project_hash:
    raise SystemExit("[site] refused: prepared plan target differs from the linked Vercel project")
if hashlib.sha256(notes.encode()).hexdigest() != plan.get("notes_sha256"):
    raise SystemExit("[site] refused: release notes changed after preparation")
if hashlib.sha256(manifest).hexdigest() != plan.get("manifest_sha256"):
    raise SystemExit("[site] refused: publication manifest changed after preparation")
PY
  STAGED="$ARTIFACTS/publication/$HASH"
  [[ -d "$STAGED/.vercel/output" && -f "$STAGED/.vercel/output/config.json" ]] || { echo "[site] refused: staged publication $HASH is missing" >&2; exit 1; }
  if [[ -f "$SIGMA/.vercel/project.json" ]]; then
    [[ -f "$STAGED/.vercel/project.json" ]] && cmp -s "$SIGMA/.vercel/project.json" "$STAGED/.vercel/project.json" \
      || { echo "[site] refused: staged publication belongs to a different Vercel project" >&2; exit 1; }
  fi
  VERIFY_HASH=$("$PYTHON" - "$STAGED/.vercel/output" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    name = path.relative_to(root).as_posix().encode()
    payload = path.read_bytes()
    digest.update(len(name).to_bytes(8, "big"))
    digest.update(name)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
print(digest.hexdigest())
PY
)
  [[ $VERIFY_HASH == "$HASH" ]] || { echo "[site] refused: staged publication does not match its hash" >&2; exit 1; }
  audit_publication "$STAGED/.vercel/output" || { echo "[site] refused: staged publication contains a private path" >&2; exit 1; }
else
  SOURCE=$(mktemp -d "${TMPDIR:-/tmp}/sigma-vercel-build.XXXXXX")
  git -C "$SIGMA" archive "$SOURCE_SHA" | tar -x -C "$SOURCE"
  mkdir -p "$SOURCE/.vercel"
  [[ ! -f "$SIGMA/.vercel/project.json" ]] || cp "$SIGMA/.vercel/project.json" "$SOURCE/.vercel/project.json"
  BUILD_DATA_ROOT="$DATA_ROOT"
  if [[ $MODE == --preflight ]]; then
    SNAPSHOT_PARENT="${SIGMA_PUBLICATION_DATA_SNAPSHOT_ROOT:-${TMPDIR:-/tmp}}"
    mkdir -p "$SNAPSHOT_PARENT"
    BUILD_DATA_ROOT=$(mktemp -d "$SNAPSHOT_PARENT/sigma-publication-data.XXXXXX")
    (cd "$SOURCE" && SIGMA_DATA_ROOT="$DATA_ROOT" PYTHONPATH=. "$PYTHON" - "$DATA_ROOT" "$BUILD_DATA_ROOT" <<'PY'
import sys
from sigma.published import freeze_publication_inputs

freeze_publication_inputs(sys.argv[1], sys.argv[2])
print("[site] source-grounded publication inputs accepted")
PY
    )
  fi
  if [[ -z $BASE_URL ]]; then
    BASE_URL=$(cd "$SOURCE" && SIGMA_DATA_ROOT="$BUILD_DATA_ROOT" SIGMA_SITE_CONFIG="$BUILD_DATA_ROOT/site.json" PYTHONPATH=. "$PYTHON" -m sigma.site_config) \
      || { echo "[site] could not resolve the configured base URL from staged source" >&2; exit 1; }
  fi
  OUTPUT="$SOURCE/.vercel/output"
  PYTHON_PATH=${PYTHON:h}
  if (cd "$SOURCE" && PATH="$PYTHON_PATH:$PATH" SIGMA_DATA_ROOT="$BUILD_DATA_ROOT" SIGMA_X_DIR="$BUILD_DATA_ROOT/x" SIGMA_SITE_CONFIG="$BUILD_DATA_ROOT/site.json" SIGMA_BASE_URL="$BASE_URL" vercel build --prod) >"$BUILD_OUT" 2>"$BUILD_ERR"; then
    :
  else
    rc=$?
    echo "[site] local production build failed (vercel exit $rc):"
    cat "$BUILD_OUT" "$BUILD_ERR"
    exit "$rc"
  fi
  [[ -d $OUTPUT && -f $OUTPUT/config.json ]] || { echo "[site] refused: vercel build produced no complete .vercel/output" >&2; exit 1; }
  audit_publication "$OUTPUT" || { echo "[site] refused: generated publication contains a private path" >&2; exit 1; }
  HASH=$("$PYTHON" - "$OUTPUT" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    name = path.relative_to(root).as_posix().encode()
    payload = path.read_bytes()
    digest.update(len(name).to_bytes(8, "big"))
    digest.update(name)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
print(digest.hexdigest())
PY
  )
  echo "[site] production build content: $HASH"
  STAGED="$ARTIFACTS/publication/$HASH"
  if [[ -d "$STAGED/.vercel/output" ]]; then
    STAGED_HASH=$("$PYTHON" - "$STAGED/.vercel/output" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    name = path.relative_to(root).as_posix().encode()
    payload = path.read_bytes()
    digest.update(len(name).to_bytes(8, "big"))
    digest.update(name)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
print(digest.hexdigest())
PY
    )
    [[ $STAGED_HASH == "$HASH" ]] || { echo "[site] refused: saved publication content does not match its hash" >&2; exit 1; }
  else
    mkdir -p "$STAGED/.vercel"
    cp -R "$OUTPUT" "$STAGED/.vercel/output"
  fi
  if [[ -f "$SIGMA/.vercel/project.json" ]]; then
    if [[ -f "$STAGED/.vercel/project.json" ]]; then
      cmp -s "$SIGMA/.vercel/project.json" "$STAGED/.vercel/project.json" || { echo "[site] refused: saved publication belongs to a different Vercel project" >&2; exit 1; }
    else
      cp "$SIGMA/.vercel/project.json" "$STAGED/.vercel/project.json"
    fi
  fi
fi
if [[ $MODE == --preflight || $MODE == --dry-run ]]; then
  if [[ -f $STAMP && "$(cat "$STAMP")" == "$HASH" ]]; then
    echo "[site] unchanged; no deployment needed"
  elif [[ $MODE == --preflight ]] && (( USED >= MAX )); then
    echo "[site] refused: already made today's $MAX deployments ($TODAY); next publication can deploy it" >&2
    exit 1
  else
    echo "[site] changed; dry run, no deployment uploaded"
  fi
  exit 0
fi
if [[ -f $STAMP && "$(cat "$STAMP")" == "$HASH" ]]; then
  echo "[site] unchanged since last deployment; not deployed"
  exit 0
fi
if (( USED >= MAX )); then
  echo "[site] refused: already made today's $MAX deployments ($TODAY); next publication can deploy it" >&2
  exit 1
fi
OUT="$SIGMA/.vercel/deploy.out"
ERR="$SIGMA/.vercel/deploy.err"
url=""
rc=0
attempt() {
  rc=0; url=""
  VERIFY_HASH=$("$PYTHON" - "$STAGED/.vercel/output" <<'PY'
import hashlib
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    name = path.relative_to(root).as_posix().encode()
    payload = path.read_bytes()
    digest.update(len(name).to_bytes(8, "big"))
    digest.update(name)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)
print(digest.hexdigest())
PY
)
  if [[ $VERIFY_HASH != "$HASH" ]]; then
    rc=91
    echo "staged publication changed after its content hash" >"$ERR"
    : >"$OUT"
    echo "[site] refused: staged publication changed after its content hash" >&2
    return 1
  fi
  (cd "$STAGED" && vercel deploy --prebuilt --prod --yes) >"$OUT" 2>"$ERR" || rc=$?
  url=$(grep -Eo 'https://[^ "<>]+' "$OUT" | tail -1 || true)
  [[ $rc -eq 0 && $url == https://* ]] && return 0
  if [[ $url == https://* ]]; then
    echo "$TODAY $HASH" >>"$LOG"
    USED=$((USED + 1))
  fi
  {
    echo "=== $(date '+%F %T %Z') attempt $1: vercel exit $rc; ${HASH:0:12}; url '${url:-none}'"
    echo "--- stdout"; cat "$OUT"; echo "--- stderr"; cat "$ERR"
  } >>"$FAILLOG"
  echo "[site] deploy attempt $1 failed (vercel exit $rc). stdout, then stderr:" >&2
  { echo "--- stdout"; tail -20 "$OUT"; echo "--- stderr"; tail -20 "$ERR"; } >&2
  return 1
}
attempt 1 || {
  if (( USED >= MAX )); then
    echo "[site] not retrying: the failed attempt used the day's last deploy ($USED of $MAX on $TODAY); full output in $FAILLOG" >&2
    exit 1
  fi
  WAIT=${SIGMA_DEPLOY_RETRY_SLEEP:-15}
  echo "[site] retrying once in ${WAIT}s" >&2
  sleep "$WAIT"
  attempt 2 || { echo "[site] deploy failed twice (vercel exit $rc); full output in $FAILLOG" >&2; exit 1; }
}
echo "$HASH" >"$STAMP"
echo "$TODAY $HASH" >>"$LOG"
echo "[site] deployed: $url"
