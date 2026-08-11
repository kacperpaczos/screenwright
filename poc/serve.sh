#!/bin/bash
# Local image server for testing screenshot substitution in a software centre.
#   ./serve.sh start | stop | status
# The server is detached with setsid, so it outlives the session that started it.

DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIA="$DIR/media"
PORT=8899
PIDFILE="$DIR/.serve.pid"
LOG="$DIR/.serve.log"

case "${1:-status}" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already running, pid $(cat "$PIDFILE")"; exit 0
    fi
    setsid nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$MEDIA" \
      >"$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    sleep 1
    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "started on 127.0.0.1:$PORT, pid $(cat "$PIDFILE")"
    else
      echo "failed to start, see $LOG"; exit 1
    fi
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null && echo "stopped"
      rm -f "$PIDFILE"
    else
      echo "not running"
    fi
    ;;
  status)
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 \
           "http://127.0.0.1:$PORT/kcalc-source.png")
    [ "$code" = "200" ] && echo "running (HTTP $code)" || echo "not responding (HTTP $code)"
    ;;
  *)
    echo "usage: $0 start|stop|status"; exit 2
    ;;
esac
