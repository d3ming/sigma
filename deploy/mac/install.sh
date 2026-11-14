#!/bin/bash
# One-time: install the launchd agents for the weekday and Sunday runs (times: StartCalendarInterval in each plist). Does not use sudo.
# Usage: install.sh [daily] [weekly]   (default: both). SIGMA_HEAVY_LOCK, when set, overrides the jobs' whisper lock path.
set -euo pipefail
REPO="${SIGMA_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
DATA_ROOT="${SIGMA_DATA_ROOT:-$REPO/data}"
mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
chmod +x "$REPO/deploy/mac/run-daily.sh" "$REPO/deploy/mac/run-weekly.sh"
escape_sed() { printf '%s' "$1" | sed 's/[\\&#]/\\&/g'; }
REPO_VALUE=$(escape_sed "$REPO")
DATA_VALUE=$(escape_sed "$DATA_ROOT")
JOBS=("$@"); [ ${#JOBS[@]} -gt 0 ] || JOBS=(daily weekly)
for JOB in "${JOBS[@]}"; do
  LABEL="com.sigma.$JOB"
  [ -f "$REPO/deploy/mac/$LABEL.plist" ] || { echo "unknown job: $JOB (daily or weekly)" >&2; exit 2; }
  DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
  sed -e "s#__SIGMA_REPO__#$REPO_VALUE#g" -e "s#__SIGMA_DATA_ROOT__#$DATA_VALUE#g" "$REPO/deploy/mac/$LABEL.plist" > "$DEST"
  [ -z "${SIGMA_HEAVY_LOCK:-}" ] || plutil -insert EnvironmentVariables.SIGMA_HEAVY_LOCK -string "$SIGMA_HEAVY_LOCK" "$DEST"
  plutil -lint "$DEST"
  launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$DEST"
  launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|path" | head -3
done
cat <<MSG

Installed ${JOBS[*]} at the times in each plist's StartCalendarInterval (daily: weekdays; weekly: Sundays).
A run missed while the Mac sleeps fires on the next wake. No scheduled wake is needed for afternoon jobs.

Test now:  launchctl kickstart -k gui/$(id -u)/com.sigma.${JOBS[0]}   (logs: $REPO/logs/run-<run>.log)
MSG
