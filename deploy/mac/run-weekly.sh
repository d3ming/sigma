#!/bin/bash
# Sunday 14:30 Mac run: fetch the last 7 days and whisper every episode (MLX). The 15:30 agent task ranks,
# writes themes and publishes. --refetch because the weekday runs already marked most episodes as seen;
# transcribe reuses their transcripts, so only the rest is whispered.
# Usage: run-weekly.sh [run-name]   (default: this week's Monday + -weekly). Safe to rerun; transcribe is resumable.
set -uo pipefail
REPO="${PA_REPO:-$HOME/projects/wire}"
cd "$REPO" || exit 1
mkdir -p logs
RUN="${1:-$(date -v-"$(( ($(date +%u) + 6) % 7 ))"d +%Y-%m-%d)-weekly}"
LOG="logs/run-$RUN.log"
PA="$REPO/.venv/bin/wire"
export PA_WHISPER_BACKEND="${PA_WHISPER_BACKEND:-mlx}"
export WIRE_BY=launchd  # the event log labels every wire command below
exec >>"$LOG" 2>&1
echo "== $(date '+%F %T %Z') weekly $RUN backend=$PA_WHISPER_BACKEND"

# One line in data/events/ per outcome. `wire event` always exits 0; the || true keeps a missing binary from changing this script.
ev() { "$PA" event launchd_weekly --run "$RUN" "$@" >/dev/null 2>&1 || true; }
fail() { echo "FAILED: $1"; ev --status fail --dur "$SECONDS" --err "$1"; exit 1; }
ev --status start

caffeinate -dimsu -w $$ &
git checkout -q develop && git pull --ff-only -q || { echo "warn: git pull failed; running current checkout"; ev --status warn --warn "git pull failed; ran the current checkout"; }
[ -f "runs/$RUN/manifest.json" ] || "$PA" fetch --days 7 --refetch --run-name "$RUN" \
  || fail "fetch"
"$PA" transcribe "runs/$RUN" --top 0 --minutes 6000 --backend "$PA_WHISPER_BACKEND" || fail "transcribe"
ev --status ok --dur "$SECONDS"
echo "== $(date '+%F %T %Z') done"
