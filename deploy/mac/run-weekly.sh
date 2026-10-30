#!/bin/bash
# Sunday 14:30 Mac run: fetch the last 7 days and whisper every episode (MLX). The 15:30 agent task ranks,
# writes themes and publishes. --refetch because the weekday runs already marked most episodes as seen;
# transcribe reuses their transcripts, so only the rest is whispered.
# Usage: run-weekly.sh [run-name]   (default: this week's Monday + -weekly). Safe to rerun; transcribe is resumable.
set -uo pipefail
REPO="${SIGMA_REPO:-$HOME/projects/sigma}"
cd "$REPO" || exit 1
DATA_ROOT="${SIGMA_DATA_ROOT:-$REPO/data}"
mkdir -p logs
RUN="${1:-$(date -v-"$(( ($(date +%u) + 6) % 7 ))"d +%Y-%m-%d)-weekly}"
RUN_DIR="$DATA_ROOT/runs/$RUN"
LOG="logs/run-$RUN.log"
PA="$REPO/.venv/bin/sigma"
export SIGMA_WHISPER_BACKEND="${SIGMA_WHISPER_BACKEND:-mlx}"
export SIGMA_BY=launchd  # the event log labels every sigma command below
exec >>"$LOG" 2>&1
echo "== $(date '+%F %T %Z') weekly $RUN backend=$SIGMA_WHISPER_BACKEND"

ev() { "$PA" event launchd_weekly --run "$RUN" "$@" >/dev/null 2>&1 || true; }
fail() { echo "FAILED: $1"; ev --status fail --dur "$SECONDS" --err "$1"; exit 1; }
ev --status start

caffeinate -dimsu -w $$ &
git checkout -q develop && git pull --ff-only -q || { echo "warn: git pull failed; running current checkout"; ev --status warn --warn "git pull failed; ran the current checkout"; }
[ -f "$RUN_DIR/manifest.json" ] || "$PA" fetch --days 7 --refetch --run-name "$RUN" \
  || fail "fetch"
"$PA" transcribe "$RUN_DIR" --top 0 --minutes 6000 --backend "$SIGMA_WHISPER_BACKEND" || fail "transcribe"
ev --status ok --dur "$SECONDS"
echo "== $(date '+%F %T %Z') done"
