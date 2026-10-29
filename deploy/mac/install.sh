#!/bin/bash
# One-time: install the launchd agents for the weekday and Sunday 14:30 runs. Does not use sudo.
set -euo pipefail
REPO="$HOME/projects/wire"
mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
chmod +x "$REPO/deploy/mac/run-daily.sh" "$REPO/deploy/mac/run-weekly.sh"
for LABEL in com.dming.podcast-alpha com.dming.podcast-alpha.weekly; do
  DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
  sed "s#__HOME__#$HOME#g" "$REPO/deploy/mac/$LABEL.plist" > "$DEST"
  plutil -lint "$DEST"
  launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$DEST"
  launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|path" | head -3
done
cat <<MSG

Installed com.dming.podcast-alpha (weekdays 14:30) and com.dming.podcast-alpha.weekly (Sundays 14:30).
A run missed while the Mac sleeps fires on the next wake. No scheduled wake is needed for afternoon jobs.

Test now:  launchctl kickstart -k gui/$(id -u)/com.dming.podcast-alpha ; tail -f $REPO/logs/run-\$(date +%F).log
MSG
