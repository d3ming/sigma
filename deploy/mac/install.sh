#!/bin/bash
# One-time: install the launchd agents for the weekday and Sunday 14:30 runs. Does not use sudo.
set -euo pipefail
REPO="${SIGMA_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
DATA_ROOT="${SIGMA_DATA_ROOT:-$REPO/data}"
mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
chmod +x "$REPO/deploy/mac/run-daily.sh" "$REPO/deploy/mac/run-weekly.sh"
escape_sed() { printf '%s' "$1" | sed 's/[\\&#]/\\&/g'; }
REPO_VALUE=$(escape_sed "$REPO")
DATA_VALUE=$(escape_sed "$DATA_ROOT")
for LABEL in com.sigma.daily com.sigma.weekly; do
  DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
  sed -e "s#__SIGMA_REPO__#$REPO_VALUE#g" -e "s#__SIGMA_DATA_ROOT__#$DATA_VALUE#g" "$REPO/deploy/mac/$LABEL.plist" > "$DEST"
  plutil -lint "$DEST"
  launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$DEST"
  launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|path" | head -3
done
cat <<MSG

Installed com.sigma.daily (weekdays 14:30) and com.sigma.weekly (Sundays 14:30).
A run missed while the Mac sleeps fires on the next wake. No scheduled wake is needed for afternoon jobs.

Test now:  launchctl kickstart -k gui/$(id -u)/com.sigma.daily ; tail -f $REPO/logs/run-\$(date +%F).log
MSG
