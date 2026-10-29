#!/usr/bin/env bash
# Local preview of the site on http://localhost:8787, rebuilt whenever the code or published data changes.
#   scripts/preview.sh start|stop|restart|status|logs|run      (default: status)
#   scripts/preview.sh install|uninstall                        keep it running across logins (macOS LaunchAgent)
# `make preview` restarts it. The port is PREVIEW_PORT (default 8787). Log: .preview/preview.log
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PREVIEW_PORT:-8787}"
DIR=".preview"; PIDF="$DIR/preview.pid"; LOG="$DIR/preview.log"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"
LABEL="com.dming.wire-preview"; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$DIR"

alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
up() { curl -fs -o /dev/null "http://localhost:$PORT/" 2>/dev/null; }

start() {
  if alive; then echo "already running: pid $(cat "$PIDF") on http://localhost:$PORT/"; return; fi
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then echo "port $PORT is taken by another process" >&2; exit 1; fi
  PREVIEW_PORT="$PORT" nohup "$PY" scripts/preview_server.py --port "$PORT" >>"$LOG" 2>&1 </dev/null &
  echo $! >"$PIDF"; disown 2>/dev/null || true
  for _ in $(seq 1 60); do up && break; alive || { echo "failed to start; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }; sleep 0.5; done
  echo "preview: http://localhost:$PORT/  (pid $(cat "$PIDF"), log $LOG)"
}
stop() { if alive; then kill "$(cat "$PIDF")"; sleep 0.3; echo "stopped"; else echo "not running"; fi; rm -f "$PIDF"; }

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) if alive && up; then echo "running: http://localhost:$PORT/ (pid $(cat "$PIDF"))"; else echo "not running"; fi ;;
  logs) tail -n 40 -f "$LOG" ;;
  run) exec "$PY" scripts/preview_server.py --port "$PORT" ;;
  install)
    stop || true
    mkdir -p "$(dirname "$PLIST")"
    cat >"$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array><string>$PWD/$PY</string><string>$PWD/scripts/preview_server.py</string><string>--port</string><string>$PORT</string></array>
<key>WorkingDirectory</key><string>$PWD</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$PWD/$LOG</string><key>StandardErrorPath</key><string>$PWD/$LOG</string>
</dict></plist>
PL
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "installed $PLIST; http://localhost:$PORT/" ;;
  uninstall) launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; rm -f "$PLIST"; echo "uninstalled" ;;
  *) echo "usage: scripts/preview.sh start|stop|restart|status|logs|run|install|uninstall" >&2; exit 2 ;;
esac
