#!/bin/zsh
# Deploy wire.dming.si from origin/main (production is main; day-to-day work is on develop and reaches main by a
# fast-forward release, see AGENTS.md). Refuses unless this clone is on main, at origin/main.
# At most once per commit, and at most WIRE_DEPLOYS_PER_DAY (2) per Pacific day. Git pushes do not deploy: the Vercel Hobby plan allows 100 deployments a day per account, and a skipped build still counts. Wire
# publishes twice on weekdays, an X-only edition by 8:00 AM and the podcasts plus X by 5:00 PM, and each publish is one
# deploy (`make release-land` runs this script). .vercel/deploys holds one "<Pacific date> <sha>" line per deploy made,
# forced or not; a third deploy in the day is refused. --force is for a deploy the owner asks for: it deploys even if this
# commit already went out or the day's two are used up (it is still recorded). `--quota [sha]` only reports, and
# release.sh land asks it before it moves main: exit 1 only when the day's deploys are used up and [sha] (default origin/main)
# would change what the site builds from since the last deploy; a release that changes nothing the site reads needs no deploy.
# Uploads `git archive origin/main`, never the working tree: data/ and runs/ are private.
set -euo pipefail
WIRE="${0:A:h:h:h}"
cd "$WIRE"
LOG="$WIRE/.vercel/deploys"         # .vercel/ is git-ignored and local to this Mac
TODAY=$(TZ=America/Los_Angeles date +%F)
MAX=${WIRE_DEPLOYS_PER_DAY:-2}
USED=$(grep -c "^$TODAY " "$LOG" 2>/dev/null || true); USED=${USED:-0}
STAMP="$WIRE/.vercel/deployed-sha"
# changes_site <sha>: 0 when <sha> differs from the last deployed commit in a path the build reads (tests, docs, prompts,
# skills, scripts and deploy tooling are not), or when there is no usable stamp.
changes_site() {
  [[ -f $STAMP ]] && git cat-file -e "$(<$STAMP)^{commit}" 2>/dev/null || return 0
  ! git diff --quiet "$(<$STAMP)" "$1" -- . ':!tests' ':!docs' ':!deploy' ':!prompts' ':!skills' ':!scripts' \
      ':!.githooks' ':!.github' ':!AGENTS.md' ':!README.md' ':!CONTRIBUTING.md' ':!SECURITY.md' ':!CODE_OF_CONDUCT.md' ':!REVIEW.md'
}
if [[ "${1:-}" == --quota ]]; then
  echo "[site] $USED of $MAX deploys used on $TODAY"
  (( USED < MAX )) || { changes_site "${2:-origin/main}" && exit 1; }
  exit 0
fi
BRANCH=$(git branch --show-current)
if [[ $BRANCH != main ]]; then
  echo "[site] refused: production deploys only from main, and this clone is on '${BRANCH:-a detached HEAD}'." >&2
  echo "Release instead: make release, review the PR, then make release-land, which runs this script from main (AGENTS.md)" >&2
  exit 1
fi
git fetch -q origin main
[[ $(git rev-parse HEAD) == $(git rev-parse origin/main) ]] \
  || { echo "[site] refused: local main is not at origin/main; git push (or git pull --ff-only) first" >&2; exit 1; }
SHA=$(git rev-parse origin/main)
if [[ "${1:-}" != --force && -f $STAMP && "$(<$STAMP)" == "$SHA" ]]; then
  echo "[site] ${SHA:0:7} already deployed"
  exit 0
fi
# A commit that changes nothing the build reads (tests, docs, prompts, skills, scripts) leaves the site as it is: no deploy.
if [[ "${1:-}" != --force && -f $STAMP ]] && ! changes_site "$SHA"; then
  echo "$SHA" >"$STAMP"
  echo "[site] ${SHA:0:7} changes nothing the site builds from; not deployed"
  exit 0
fi
if [[ "${1:-}" != --force ]] && (( USED >= MAX )); then
  echo "[site] refused: Wire already made today's $MAX deploys ($TODAY); ${SHA:0:7} goes out with the next publish. --force only when the owner asks"
  exit 1
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/site"
git archive origin/main | tar -x -C "$TMP/site"
mkdir -p "$TMP/site/.vercel"
cp .vercel/project.json "$TMP/site/.vercel/"  # the link to the project only, not the stamps or the failure log
# The URL is on stdout; progress and errors go to stderr. Reading both as one stream once took a success for a failure,
# left the commit unstamped, and every later run deployed it again (2026-10-27: 4 extra deploys). So the two streams stay
# apart, and a failure is never silent: the first release under the reviewed flow (2026-10-28) died with only the CLI banner
# on stderr and no exit code, because `|| true` ate it and the message showed the last 3 lines of a 3-line log. Now each
# attempt keeps its exit code and both streams, a failed attempt prints them (and keeps them in .vercel/deploy-failed.log,
# git-ignored, local), and one retry follows after a pause. A failed attempt that made no deployment costs no quota; only
# a CLI that lost the URL of a deployment it did make could cost a second one.
OUT="$TMP/vercel.out"; ERR="$TMP/vercel.err"; FAILLOG="$WIRE/.vercel/deploy-failed.log"
url="" rc=0
attempt() {  # attempt <n>: sets url and rc
  rc=0 url=""
  (cd "$TMP/site" && vercel deploy --prod --yes >"$OUT" 2>"$ERR") || rc=$?
  url=$(grep -Eo 'https://[^ "<>]+' "$OUT" | tail -1 || true)
  [[ $url == https://* && $rc -eq 0 ]] && return 0  # a URL with a failing exit is a build that failed after upload: not a success
  # A URL means Vercel created a deployment even though its build failed; that one counts toward the day's quota.
  [[ $url == https://* ]] && { echo "$TODAY $SHA" >>"$LOG"; USED=$((USED+1)); }
  {
    echo "=== $(date '+%F %T %Z') attempt $1: vercel exit $rc, url '${url:-none}'; ${SHA:0:7}; vercel $(vercel --version 2>&1 | tail -1); node $(node --version 2>&1)"
    echo "--- stdout"; cat "$OUT"; echo "--- stderr"; cat "$ERR"
  } >>"$FAILLOG"
  echo "[site] deploy attempt $1 failed (vercel exit $rc). stdout, then stderr, last 20 lines each:" >&2
  { echo "--- stdout"; tail -20 "$OUT"; echo "--- stderr"; tail -20 "$ERR"; } >&2
  return 1
}
attempt 1 || {
  if [[ "${1:-}" != --force ]] && (( USED >= MAX )); then
    echo "[site] not retrying: the failed attempt used the day's last deploy ($USED of $MAX on $TODAY); full output in .vercel/deploy-failed.log. main has already moved, so the only way out is deploy/mac/site-deploy.sh --force from main, and only when the owner asks" >&2
    exit 1
  fi
  echo "[site] retrying once in ${WIRE_DEPLOY_RETRY_SLEEP:-15}s" >&2
  sleep "${WIRE_DEPLOY_RETRY_SLEEP:-15}"
  attempt 2 || { echo "[site] deploy failed twice (vercel exit $rc): $(tail -2 "$ERR" "$OUT" 2>/dev/null | grep -v '^==>' | tr '\n' ' ' | cut -c1-300); full output in .vercel/deploy-failed.log"; exit 1; }
}
echo "$SHA" >"$STAMP"
echo "$TODAY $SHA" >>"$LOG"
echo "[site] deployed ${SHA:0:7}: $url"
