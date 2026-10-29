#!/usr/bin/env bash
# Release Wire: develop reaches main, and the site, only through one reviewed pull request whose exact commit was tested
# locally first. AGENTS.md has the flow; `make release` and `make release-land` run this.
#   scripts/release.sh [--dry-run]   cut or refresh the candidate: point the release-candidate branch at origin/develop's tip,
#                                    open or refresh its PR into main, test that exact commit in a detached worktree (the
#                                    suite, then a local preview on a spare port and the routes below), post the result on the PR.
#                                    --dry-run does the same but pushes and posts nothing: it prints the PR body and the comment.
#   scripts/release.sh land          land the candidate: fast-forward main to the PR head, deploy, check the live site, comment.
# The PR's head is release-candidate, not develop, so the operator's and bots' pushes to develop after the cut do not move
# what was tested; they go out in the next release. Landing needs both, for the PR's current head:
#   - the newest release-check comment is a pass naming that SHA (fixes land on develop; `make release` refreshes the PR);
#   - a comment line `LGTM <sha>` (7 to 40 hex characters of that SHA) from an account with write access, in a comment that
#     also has a `reviews:` line linking or summing up the two independent reviews of that SHA (AGENTS.md, To release). A
#     comment, not an approving review: the release PR is opened by the account the agents share, and GitHub never lets a
#     PR's author approve it. For the same reason the gate cannot tell who wrote the LGTM; the rule in AGENTS.md is the check.
# The deploy is site-deploy.sh, which allows 2 deploys a Pacific day (the 8:00 AM X edition and the 5:00 PM issue; AGENTS.md)
# and skips a release that changes nothing the site builds from. Land asks `site-deploy.sh --quota <sha>` before it moves
# main, so a release that would need a third deploy is refused with main untouched. WIRE_DEPLOY_FORCE=1 (a deploy the
# owner asked for) lifts that and passes --force.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"  # a worktree has no .venv of its own: use the main checkout's
PY=python3
for v in "$ROOT/.venv" "$MAIN/.venv"; do [ -x "$v/bin/python" ] && { PY="$v/bin/python"; break; }; done
SITE="${WIRE_SITE_URL:-https://wire.dming.si}"
CAND=release-candidate
TMP=$(mktemp -d); WT=""; SERVER=""; BACK_TO_DEVELOP=""

cleanup() {
  [ -z "$SERVER" ] || kill "$SERVER" 2>/dev/null || true
  [ -z "$WT" ] || git worktree remove --force "$WT" 2>/dev/null || true
  if [ -n "$BACK_TO_DEVELOP" ]; then
    git checkout -q develop || echo "[release] could not return this clone to develop: git checkout develop" >&2
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT
say() { echo "[release] $*"; }
# tick <step> start|end: one line in the run's step log (wire/steplog.py, `wire step table` prints it). It never fails a release.
STEPLOG=$(cd "$ROOT" && PYTHONPATH=. "$PY" -c 'from wire.steplog import log_path; print(log_path())' 2>/dev/null) || STEPLOG=""
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

# dates <sha>: the newest daily run, X edition and Alpha day in that commit's published/ (empty when it has none).
dates() {
  RUN=$(git ls-tree --name-only "$1" published/ | sed -n 's|^published/\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)$|\1|p' | tail -1)
  XD=$(git ls-tree --name-only "$1" published/x/editions/ | sed -n 's|.*/\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)\.json$|\1|p' | tail -1)
  AD=$(git ls-tree --name-only "$1" published/alpha/ | sed -n 's|.*/\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)\.json$|\1|p' | tail -1)
}

# route <label> <url> [wire verify flags]: one table row. `wire verify` from $CODE (the candidate's code) does the GET and
# the content check; $NO_EVENTS keeps a local check out of the event log.
route() {
  local name=$1 url=$2 out r=PASS; shift 2
  out=$(cd "$CODE" && PA_NO_EVENTS="$NO_EVENTS" PYTHONPATH=. "$PY" -m wire.cli verify "$url" "$@" 2>&1) || { r=FAIL; FAILS=$((FAILS + 1)); }
  echo "| \`$name\` | $r | $(echo "$out" | sed -e "s|$BASE_URL||g" -e 's/^\[verify\] //' -e 's/|/\\|/g' | paste -sd ';' - | sed 's/;/; /g') |"
}

# smoke <base url> <sha>: the routes a reader and an agent hit first, checked against what commit <sha> published.
smoke() {
  BASE_URL=${1%/}; FAILS=0
  dates "$2"
  if [ -n "$RUN" ]; then route / "$BASE_URL/" --run "$RUN"; else route / "$BASE_URL/" --expect '</html>'; fi
  if [ -n "$XD" ]; then
    local label; label=$(cd "$CODE" && PYTHONPATH=. "$PY" -c 'import sys; from wire.site import human_date; print(human_date(sys.argv[1]))' "$XD")
    route /x "$BASE_URL/x" --expect "<title>X $label "
    route "/x/$XD/" "$BASE_URL/x/$XD/" --expect "<title>X $label "
  fi
  route /llms.txt "$BASE_URL/llms.txt" --expect '# Wire'
  [ -z "$AD" ] || route "/alpha/index.json, /alpha/$AD.json" "$BASE_URL" --alpha "$AD"  # --alpha takes the site root
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
  echo "## Published data"
  echo
  git diff --name-only "$BASE" "$SHA" -- published/ | awk -F/ '
    { if ($2 == "alpha" || $2 == "x") { k = $2; for (i = 3; i < NF; i++) k = k "/" $i; f = $NF; sub(/\..*/, "", f) } else { k = "runs"; f = $2 }
      if (!((k, f) in seen)) { seen[k, f] = 1; v[k] = (k in v ? v[k] ", " : "") "`" f "`" } }
    END { for (k in v) print "- " k ": " v[k] }' | sort
  git diff --quiet "$BASE" "$SHA" -- published/ && echo "None."
  echo
  echo "## Code and docs changed"
  echo
  git diff --name-status "$BASE" "$SHA" -- . ':!published' | awk -F'\t' 'NR <= 150 { print "- " $1 " `" $NF "`" }'
  git diff --quiet "$BASE" "$SHA" -- . ':!published' && echo "None."
  echo
  echo "## Checklist"
  echo
  echo "- [ ] The newest release check below passed on this head"
  echo "- [ ] Commits and code changes read; anything the site shows differently looked at on the local preview (\`make preview\` on develop)"
  echo "- [ ] Every review finding fixed on \`develop\`, then \`make release\` refreshed this PR and checked the new head"
  echo "- [ ] Two independent reviews (Codex and Bellatrix, REVIEW.md) cleared this head, each posted on this PR"
  echo "- [ ] A comment line \`LGTM <sha>\` names this head, with a \`reviews:\` line linking or summing up both reviews"
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
    echo "<!-- wire-release-check sha=$SHA result=$result -->"
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
      echo "Landable once two independent reviews clear it: comment \`LGTM ${SHA:0:12}\` with a \`reviews:\` line, then \`make release-land\`."
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
checks = [m for b in bodies for m in re.findall(r"<!-- wire-release-check sha=([0-9a-f]{40}) result=(pass|fail) -->", b)]
sha, result = checks[-1] if checks else ("none", "none")
ok = any(head.startswith(p) for b in bodies if "reviews:" in b for p in re.findall(r"(?m)^\s*LGTM ([0-9a-f]{7,40})\s*$", b))
print(head, sha, result, "yes" if ok else "no")' "$TMP/pr.json" "$writers_only")
  [ "$checked" = "$head" ] && [ "$result" = pass ] \
    || die "PR #$pr's head is ${head:0:12}, but the newest release check is $result at ${checked:0:12}; run make release"
  [ "$lgtm" = yes ] || die "PR #$pr has no comment from an account with write access holding a line 'LGTM ${head:0:12}' and 'reviews:' (AGENTS.md, To release)"
  git merge-base --is-ancestor origin/main "$head" || die "origin/main is not an ancestor of ${head:0:12}; main only ever fast-forwards"

  # Publish exactly the approved commit. A local main holding commits of its own would make the fast-forward a no-op
  # ("already up to date") and push code nobody reviewed, so it is refused, not reset: those commits are someone's work.
  if git rev-parse -q --verify refs/heads/main >/dev/null && ! git merge-base --is-ancestor main "$head"; then
    die "local main has commits that are not in ${head:0:12}; move them to develop (git log ${head:0:12}..main), then rerun"
  fi
  tick "land: ff main and push" start
  local force=""
  [ -z "${WIRE_DEPLOY_FORCE:-}" ] || force=--force
  [ -n "$force" ] || deploy/mac/site-deploy.sh --quota "$head" \
    || die "the day's deploys are used up and ${head:0:12} changes the site; it waits for the next publish (WIRE_DEPLOY_FORCE=1 only when the owner asks). main is untouched"
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
  deploy/mac/site-deploy.sh $force >"$TMP/deploy.log" 2>&1 || deploy=FAIL
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
