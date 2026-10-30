#!/bin/bash
# Weekday 14:30 Mac run: pull code, fetch + whisper (MLX), so it is done before the 15:30 agent routine selects, reports and publishes
# the podcast issue with the X edition, live by 17:00. The window is 72 h (96 h on Monday, so the weekend is covered); seen episodes are skipped, so the overlap costs nothing and a weekly show that posted 2 days ago is not missed.
# Usage: run-daily.sh [run-name]   (default: today's local date). Safe to rerun; daily/transcribe are resumable.
set -uo pipefail
# The whole script is one function: bash reads a script as it runs, so the `git pull` below would otherwise rewrite this file
# under the running shell and break it mid-run (seen 2026-10-28). A function is parsed before it starts.
main() {
REPO="${SIGMA_REPO:-$HOME/projects/sigma}"
cd "$REPO" || exit 1
mkdir -p logs
RUN="${1:-$(date +%Y-%m-%d)}"
LOG="logs/run-$RUN.log"
PA="$REPO/.venv/bin/sigma"
export SIGMA_WHISPER_BACKEND="${SIGMA_WHISPER_BACKEND:-mlx}"
export SIGMA_PYTHON="${SIGMA_PYTHON:-$REPO/.venv/bin/python}"
export SIGMA_BY=launchd  # the event log labels every sigma command below (the queued transcribe inherits it)
exec >>"$LOG" 2>&1
echo "== $(date '+%F %T %Z') run $RUN backend=$SIGMA_WHISPER_BACKEND"

ev() { "$PA" event launchd_daily --run "$RUN" "$@" >/dev/null 2>&1 || true; }
fail() { echo "FAILED: $1"; ev --status fail --dur "$SECONDS" --err "$1"; exit 1; }
ev --status start

# caffeinate keeps the Mac awake until this script exits (transcribe included).
caffeinate -dimsu -w $$ &

git checkout -q develop && git pull --ff-only -q || { echo "warn: git pull failed; running current checkout"; ev --status warn --warn "git pull failed; ran the current checkout"; }
HOURS=72; [ "$(date +%u)" = 1 ] && HOURS=96
OUT=$("$PA" daily --hours "$HOURS" --run-name "$RUN" --backend "$SIGMA_WHISPER_BACKEND" 2>&1) || { echo "$OUT"; fail "daily exited non-zero"; }
echo "$OUT"
# Stay alive (and so keep caffeinate holding the Mac awake) until the queued transcribe finishes.
PID=$(printf '%s\n' "$OUT" | sed -n 's/.*transcribe queued pid=\([0-9]*\).*/\1/p' | tail -1)
[ -n "$PID" ] && while kill -0 "$PID" 2>/dev/null; do sleep 60; done
ev --status ok --dur "$SECONDS"
echo "== $(date '+%F %T %Z') done"
}
main "$@"
exit $?
