#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"  # a worktree has no .venv of its own: use the main checkout's
PY=python3
for v in "$ROOT/.venv" "$MAIN/.venv"; do [ -x "$v/bin/python" ] && { PY="$v/bin/python"; break; }; done
export SIGMA_DATA_ROOT="${SIGMA_DATA_ROOT:-$ROOT/data}"
SITE="${SIGMA_BASE_URL:-}"
if [ -z "$SITE" ]; then SITE=$(cd "$ROOT" && SIGMA_DATA_ROOT="${SIGMA_DATA_ROOT:-$ROOT/data}" PYTHONPATH=. "$PY" -m sigma.site_config); fi
SITE=${SITE%/}
CAND=release-candidate
TMP=$(mktemp -d "${TMPDIR:-/tmp}/sigma-release.XXXXXX"); WT=""; PREFLIGHT_WT=""; SERVER=""; BACK_TO_DEVELOP=""

cleanup() {
  [ -z "$SERVER" ] || kill "$SERVER" 2>/dev/null || true
  [ -z "$WT" ] || git worktree remove "$WT" 2>/dev/null || true
  [ -z "$PREFLIGHT_WT" ] || git worktree remove "$PREFLIGHT_WT" 2>/dev/null || true
  if [ -n "$BACK_TO_DEVELOP" ]; then
    git checkout -q develop || echo "[release] could not return this clone to develop: git checkout develop" >&2
  fi
}
trap cleanup EXIT
say() { echo "[release] $*"; }
# tick <step> start|end: one line in the run's step log (sigma/steplog.py, `sigma step table` prints it). It never fails a release.
STEPLOG=$(cd "$ROOT" && PYTHONPATH=. "$PY" -c 'from sigma.steplog import log_path; print(log_path())' 2>/dev/null) || STEPLOG=""
[ -z "$STEPLOG" ] || mkdir -p "$(dirname "$STEPLOG")" 2>/dev/null || STEPLOG=""
tick() { [ -z "$STEPLOG" ] || printf '{"step":"release: %s","event":"%s","at":"%s"}\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" >>"$STEPLOG" 2>/dev/null || true; }
die() { echo "[release] refused: $*" >&2; exit 1; }
pacific() { TZ=America/Los_Angeles date "+%Y-%m-%d %H:%M %Z"; }
# redact: the PR is public, and a preview traceback or Vercel's error text can carry this machine's paths and user name.
redact() {
  local p args=()
  for p in "$WT" "$ROOT" "$MAIN"; do [ -z "$p" ] || args+=(-e "s|\(/private\)\{0,1\}$p|<repo>|g"); done  # macOS: /var is /private/var
  sed "${args[@]}" -e "s|$HOME|~|g"
}
writers_only='["OWNER","MEMBER","COLLABORATOR"]'

publication_days() {
  (cd "$CODE" && PYTHONPATH=. "$PY" - <<'PY'
from sigma.paths import data_root
from sigma.signals_site import load as load_signals
from sigma.site import load_editions
published = data_root() / "published"
days, _ = load_signals(published)
editions = load_editions(published)
print(max(days) if days else "-", editions[0]["date"] if editions else "-")
PY
  )
}

# route <label> <url> [sigma verify flags]: one table row. `sigma verify` from $CODE (the candidate's code) does the GET and
# the content check; $NO_EVENTS keeps a local check out of the event log.
route() {
  local name=$1 url=$2 out r=PASS; shift 2
  out=$(cd "$CODE" && SIGMA_NO_EVENTS="$NO_EVENTS" PYTHONPATH=. "$PY" -m sigma.cli verify "$url" "$@" 2>&1) || { r=FAIL; FAILS=$((FAILS + 1)); }
  echo "| \`$name\` | $r | $(echo "$out" | sed -e "s|$BASE_URL||g" -e 's/^\[verify\] //' -e 's/|/\\|/g' | paste -sd ';' - | sed 's/;/; /g') |"
}

# smoke <base url> <sha>: the routes a reader and an agent hit first, checked against what commit <sha> published.
smoke() {
  BASE_URL=${1%/}; FAILS=0
  route / "$BASE_URL/" --expect '</html>'
  route /llms.txt "$BASE_URL/llms.txt" --expect '# Sigma'
  local days signals_day x_day x_label
  days=$(publication_days)
  signals_day=${days%% *}
  x_day=${days#* }
  if [ "$signals_day" != - ]; then
    route "/signals/index.json, /signals/$signals_day.json" "$BASE_URL" --signals "$signals_day"
    signals_label=$(cd "$CODE" && PYTHONPATH=. "$PY" -c 'import sys; from sigma.site import human_date; print(human_date(sys.argv[1], True))' "$signals_day")
    route "/signals/$signals_day/" "$BASE_URL/signals/$signals_day/" --expect "$signals_label"
  fi
  if [ "$x_day" != - ]; then
    x_label=$(cd "$CODE" && PYTHONPATH=. "$PY" -c 'import sys; from sigma.site import human_date; print(human_date(sys.argv[1]))' "$x_day")
    route /x "$BASE_URL/x" --expect "<title>X $x_label "
    route "/x/$x_day/" "$BASE_URL/x/$x_day/" --expect "<title>X $x_label "
  fi
  [ "$FAILS" -eq 0 ]
}

# The PR body: what the release carries, so a reviewer can scope it without cloning.
body() {
  local n; n=$(git rev-list --count "$BASE..$SHA")
  echo "Candidate \`$SHA\`: the tip of \`develop\` when cut, onto \`main\` at \`${BASE:0:12}\`. \`make release\` writes this body and"
  echo "posts the release check below; a review finding is fixed on \`develop\` and \`make release\` refreshes this PR."
  echo
  echo "## Commits ($n)"
  echo
  git log -n 150 --format='- %h %s' "$BASE..$SHA"
  [ "$n" -le 150 ] || echo "- and $((n - 150)) more: \`git log ${BASE:0:12}..${SHA:0:12}\`"
  echo
  echo "## Published site"
  echo
  echo "The site is built from the private data root configured by \`SIGMA_DATA_ROOT\`; no published output is committed here."
  echo "Before landing, \`site-deploy.sh --preflight\` builds and hashes the Vercel publication content without uploading it."
  echo
  echo "## Code and docs changed"
  echo
  git diff --name-status "$BASE" "$SHA" | awk -F'\t' 'NR <= 150 { print "- " $1 " `" $NF "`" }'
  git diff --quiet "$BASE" "$SHA" && echo "None."
  echo
  echo "## Checklist"
  echo
  echo "- [ ] The newest release check below passed on this head"
  echo "- [ ] Commits and code changes read; anything the site shows differently looked at on the local preview (\`make preview\` on develop)"
  echo "- [ ] Every review finding fixed on \`develop\`, then \`make release\` refreshed this PR and checked the new head"
  echo "- [ ] The owner reviewed this exact head"
  echo "- [ ] A write-authority account commented \`LGTM <sha>\` for this head"
  echo "- [ ] \`make release-land\` from the main checkout: fast-forwards \`main\`, deploys, checks the live site, comments here"
}

cut() {
  local dry=$1 pr="" url title
  git fetch -q origin
  SHA=$(git rev-parse origin/develop); BASE=$(git rev-parse origin/main)
  git merge-base --is-ancestor "$BASE" "$SHA" \
    || die "origin/main (${BASE:0:12}) is not an ancestor of origin/develop (${SHA:0:12}); main only ever fast-forwards"
  [ "$SHA" != "$BASE" ] || { say "nothing to release: main is already at develop (${SHA:0:12})"; exit 0; }
  body >"$TMP/body.md"
  if [ -z "$dry" ]; then
    if git rev-parse -q --verify "origin/$CAND" >/dev/null && ! git merge-base --is-ancestor "origin/$CAND" "$SHA"; then
      die "origin/$CAND is not an ancestor of develop; it only ever fast-forwards, so find out why before moving it"
    fi
    tick "push and PR" start
    git push -q origin "$SHA:refs/heads/$CAND"
    title="Release $(TZ=America/Los_Angeles date +%F): develop at ${SHA:0:7}"
    pr=$(gh pr list --base main --head "$CAND" --state open --json number --jq '.[0].number // empty')
    if [ -n "$pr" ]; then
      gh pr edit "$pr" --title "$title" --body-file "$TMP/body.md" >/dev/null
      say "refreshed PR #$pr for ${SHA:0:12}"
    else
      url=$(gh pr create --base main --head "$CAND" --title "$title" --body-file "$TMP/body.md")
      pr=${url##*/}
      say "opened PR #$pr for ${SHA:0:12}: $url"
    fi
    tick "push and PR" end
  fi

  WT="$TMP/candidate"
  git worktree add -q --detach "$WT" "$SHA"
  [ ! -f "$MAIN/.private-words" ] || cp "$MAIN/.private-words" "$WT/"  # git-ignored, so the worktree lacks it
  say "testing ${SHA:0:12} in a detached worktree"
  local tests=PASS port
  tick "tests" start
  (cd "$WT" && scripts/check.sh) >"$TMP/tests.log" 2>&1 || tests=FAIL
  tick "tests" end
  tick "preview start" start
  port=$("$PY" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
  (cd "$WT" && PYTHONPATH="$WT" exec "$PY" scripts/preview_server.py --port "$port" --poll 3600) >"$TMP/preview.log" 2>&1 &
  SERVER=$!
  local i up=""
  for i in $(seq 1 240); do
    curl -fs -o /dev/null "http://127.0.0.1:$port/" && { up=1; break; }
    kill -0 "$SERVER" 2>/dev/null || break
    sleep 0.5
  done
  tick "preview start" end
  CODE=$WT; NO_EVENTS=1
  local rows result=pass
  if [ -n "$up" ]; then
    tick "preview smoke" start
    rows=$(smoke "http://127.0.0.1:$port" "$SHA") || result=fail
    tick "preview smoke" end
  else
    rows="| preview | FAIL | the local preview did not start: $(tail -3 "$TMP/preview.log" | paste -sd ' ' -) |"; result=fail
  fi
  [ "$tests" = PASS ] || result=fail
  {
    echo "<!-- sigma-release-check sha=$SHA result=$result -->"
    echo "## Release check: $(echo "$result" | tr a-z A-Z) at \`${SHA:0:12}\`"
    echo
    echo "\`make release\` tested \`$SHA\` in a detached worktree on $(pacific): the suite, then a local preview built from it."
    echo
    echo "| Check | Result | Detail |"
    echo "|---|---|---|"
    echo "| tests (\`scripts/check.sh\`) | $tests | $(grep -E 'passed|failed|error' "$TMP/tests.log" | tail -1 | sed 's/|/\\|/g') |"
    echo "$rows"
    echo
    if [ "$result" = pass ]; then
      echo "Landable after owner review: comment \`LGTM ${SHA:0:12}\`, then run \`make release-land\`."
    else
      echo "Not landable. Fix on \`develop\`, then \`make release\` again."
    fi
  } | redact >"$TMP/comment.md"
  [ "$tests" = PASS ] || { echo "--- tests ---"; tail -40 "$TMP/tests.log"; }
  if [ -n "$dry" ]; then
    echo "--- dry run: PR body (not posted) ---"; cat "$TMP/body.md"
    echo "--- dry run: release check comment (not posted) ---"; cat "$TMP/comment.md"
  else
    gh pr comment "$pr" --body-file "$TMP/comment.md" >/dev/null
    cat "$TMP/comment.md"
  fi
  say "${SHA:0:12}: $result"
  [ "$result" = pass ]
}

land() {
  [ "$(git rev-parse --absolute-git-dir)" = "$(cd "$(git rev-parse --git-common-dir)" && pwd)" ] \
    || die "run it from the main checkout ($MAIN): the deploy runs from its main branch"
  git fetch -q origin
  local pr head checked result lgtm repo deploy=PASS live=PASS
  pr=$(gh pr list --base main --head "$CAND" --state open --json number --jq '.[0].number // empty')
  [ -n "$pr" ] || die "no open release PR from $CAND; run make release"
  gh pr view "$pr" --json headRefOid,comments >"$TMP/pr.json"
  read -r head checked result lgtm < <("$PY" -c '
import json, re, sys
pr, writers = json.load(open(sys.argv[1])), json.loads(sys.argv[2])
head = pr["headRefOid"]
bodies = [c["body"] for c in pr["comments"] if c.get("authorAssociation") in writers]
checks = [m for b in bodies for m in re.findall(r"<!-- sigma-release-check sha=([0-9a-f]{40}) result=(pass|fail) -->", b)]
sha, result = checks[-1] if checks else ("none", "none")
ok = any(head.startswith(p) for b in bodies for p in re.findall(r"(?m)^\s*LGTM ([0-9a-f]{7,40})\s*$", b))
print(head, sha, result, "yes" if ok else "no")' "$TMP/pr.json" "$writers_only")
  [ "$checked" = "$head" ] && [ "$result" = pass ] \
    || die "PR #$pr's head is ${head:0:12}, but the newest release check is $result at ${checked:0:12}; run make release"
  [ "$lgtm" = yes ] || die "PR #$pr has no comment from a write-authority account with line 'LGTM ${head:0:12}'"
  git merge-base --is-ancestor origin/main "$head" || die "origin/main is not an ancestor of ${head:0:12}; main only ever fast-forwards"

  local force="" preflight=deploy/mac/site-deploy.sh preflight_output preflight_hash
  [ -z "${SIGMA_DEPLOY_FORCE:-}" ] || force=--force
  PREFLIGHT_WT="$TMP/preflight"
  git worktree add -q --detach "$PREFLIGHT_WT" "$head"
  if [ -f "$ROOT/.vercel/project.json" ]; then
    mkdir -p "$PREFLIGHT_WT/.vercel"
    cp "$ROOT/.vercel/project.json" "$PREFLIGHT_WT/.vercel/project.json"
  fi
  say "building and checking the reviewed publication content before moving main"
  if ! preflight_output=$(cd "$PREFLIGHT_WT" && SIGMA_DATA_ROOT="$SIGMA_DATA_ROOT" SIGMA_PYTHON="$PY" SIGMA_DEPLOY_STATE_DIR="$ROOT/.vercel" SIGMA_DEPLOY_ARTIFACT_DIR="$ROOT/.vercel" "$preflight" --preflight ${force:+--force}); then
    echo "$preflight_output" >&2
    die "local publication preflight failed; main is untouched"
  fi
  echo "$preflight_output"
  preflight_hash=$(echo "$preflight_output" | sed -n 's/^\[site\] production build content: \([0-9a-f]\{64\}\)$/\1/p' | tail -1)
  [[ "$preflight_hash" =~ ^[0-9a-f]{64}$ ]] || die "publication preflight did not return a full content hash; main is untouched"
  git worktree remove "$PREFLIGHT_WT"
  PREFLIGHT_WT=""

  # Publish exactly the approved commit. A local main holding commits of its own would make the fast-forward a no-op
  # ("already up to date") and push code nobody reviewed, so it is refused, not reset: those commits are someone's work.
  if git rev-parse -q --verify refs/heads/main >/dev/null && ! git merge-base --is-ancestor main "$head"; then
    die "local main has commits that are not in ${head:0:12}; move them to develop (git log ${head:0:12}..main), then rerun"
  fi
  tick "land: ff main and push" start
  BACK_TO_DEVELOP=1
  git checkout -q main
  git merge -q --ff-only "$head"
  [ "$(git rev-parse main)" = "$head" ] || die "local main is at $(git rev-parse --short main), not ${head:0:12}; nothing pushed"
  git push -q origin "$head:refs/heads/main"
  say "main is at ${head:0:12}"
  tick "land: ff main and push" end
  repo=$(gh repo view --json url --jq .url)
  local state="" i
  for i in $(seq 1 10); do
    state=$(gh pr view "$pr" --json state --jq .state)
    [ "$state" = MERGED ] && break
    sleep 3
  done
  if [ "$state" != MERGED ]; then
    gh pr close "$pr" --comment "Landed by fast-forward: main is at $repo/commit/$head. GitHub did not mark this PR merged, so it is closed here." >/dev/null
    say "GitHub did not mark PR #$pr merged; closed it with a link to the push"
  fi

  tick "land: deploy" start
  SIGMA_DEPLOY_ARTIFACT_DIR="$ROOT/.vercel" deploy/mac/site-deploy.sh --deploy-staged "$preflight_hash" $force >"$TMP/deploy.log" 2>&1 || deploy=FAIL
  tick "land: deploy" end
  cat "$TMP/deploy.log"
  CODE=$ROOT; NO_EVENTS=""
  local rows="| live check | SKIPPED | the deploy failed |"
  [ "$deploy" = PASS ] || live=SKIPPED  # the header must not say PASS for a check that never ran
  if [ "$deploy" = PASS ]; then
    tick "land: live check" start
    for i in 1 2 3 4; do  # the CDN can serve the previous build for a few seconds after a deploy
      live=PASS
      rows=$(smoke "$SITE" "$head") && break
      live=FAIL
      [ "$i" = 4 ] || sleep 20
    done
    tick "land: live check" end
  fi
  {
    echo "## Released \`${head:0:12}\`: deploy $deploy, live check $live"
    echo
    echo "\`make release-land\` fast-forwarded \`main\` to \`$head\` on $(pacific) and ran \`deploy/mac/site-deploy.sh${force:+ $force}\`:"
    echo "\`$(tail -1 "$TMP/deploy.log")\`"
    echo
    echo "| Route on $SITE | Result | Detail |"
    echo "|---|---|---|"
    echo "$rows"
  } | redact >"$TMP/comment.md"
  gh pr comment "$pr" --body-file "$TMP/comment.md" >/dev/null
  cat "$TMP/comment.md"
  [ "$deploy" = PASS ] && [ "$live" = PASS ]
}

case "${1:-}" in
  "") cut "" ;;
  --dry-run) cut 1 ;;
  land) land ;;
  *) echo "usage: scripts/release.sh [--dry-run] | land" >&2; exit 2 ;;
esac
