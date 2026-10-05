#!/usr/bin/env bash
#
# SAT-SA local dev launcher.
#
# Starts the backend adapter and the frontend dev server on free localhost
# ports, wiring the frontend's /api proxy to the backend's actual port:
#
#   ./dev.sh          start both (default ports 8000/5173 when free)
#   ./dev.sh status   show running instances
#   ./dev.sh doctor   diagnose backend/frontend/proxy wiring problems
#   ./dev.sh logs     tail both logs
#   ./dev.sh restart  stop, then start
#   ./dev.sh stop     stop instances started by this script
#
# Preferred ports can be overridden:
#
#   SATSA_BACKEND_PORT=8000 SATSA_FRONTEND_PORT=5173 ./dev.sh
#
# The dataset listing the picker offers is chosen by the backend, and a
# demonstration wants the curated set rather than every test and validation
# file in the repository:
#
#   SATSA_DATASET_MODE=demo ./dev.sh              # curated demo datasets only
#   SATSA_DEMO_DATASETS="a.csv,b.csv" SATSA_DATASET_MODE=demo ./dev.sh
#
# Full mode (the default) lists everything, which is what the test suite and
# ordinary development expect. `status` reports which mode the running backend
# was started in, so a narrow picker is never a mystery.
#
# Everything stays on 127.0.0.1. No outbound network is used.
#
# Why this exists: the UI's "local analysis service is not responding"
# means the browser could not reach the backend at all. In practice that is
# always wiring — backend not started, backend died, frontend proxying to a
# port whose backend is gone, or the wrong frontend/backend pair open in the
# browser. `start` heals those states; `doctor` names them.
#
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNDIR="/tmp/satsa-dev"
BACKEND_PID="$RUNDIR/backend.pid"
FRONTEND_PID="$RUNDIR/frontend.pid"
BACKEND_PORT_FILE="$RUNDIR/backend.port"
FRONTEND_PORT_FILE="$RUNDIR/frontend.port"

PREFER_BACKEND="${SATSA_BACKEND_PORT:-8000}"
PREFER_FRONTEND="${SATSA_FRONTEND_PORT:-5173}"

# First free TCP port on 127.0.0.1 at or above the preferred one.
free_port() {
  python3 - "$1" <<'EOF'
import socket
import sys

preferred = int(sys.argv[1])
port = preferred
while True:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            port += 1
            continue
        print(port)
        break
EOF
}

alive() {
  kill -0 "$1" 2>/dev/null
}

# GET body (empty on failure).
fetch() {
  curl -fs -m 5 "$1" 2>/dev/null || true
}

# retained_analyses + pipeline_available from a health body, or "unreachable".
health_summary() {
  python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
    print("%s|%s" % (body.get("pipeline_available"), body.get("retained_analyses")))
except Exception:
    print("unreachable")
'
}

wait_for_url() {
  local url="$1"
  local tries=60

  while [ "$tries" -gt 0 ]; do
    if curl -fs -m 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
    tries=$((tries - 1))
  done

  return 1
}

recorded_pid() {
  local file="$1"

  if [ -f "$file" ] && alive "$(cat "$file")"; then
    cat "$file"
    return 0
  fi

  return 1
}

# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

do_start() {
  mkdir -p "$RUNDIR"

  local backend_port=""
  local backend_pid=""

  if backend_pid="$(recorded_pid "$BACKEND_PID")" && [ -f "$BACKEND_PORT_FILE" ]; then
    backend_port="$(cat "$BACKEND_PORT_FILE")"

    if [ -n "$(fetch "http://127.0.0.1:$backend_port/api/health")" ]; then
      echo "backend already healthy: http://127.0.0.1:$backend_port (pid $backend_pid)"
    else
      # Our recorded process is alive but not serving: it is wedged or it
      # never finished starting. Restart it rather than stacking another.
      echo "backend pid $backend_pid is alive but not serving :$backend_port — restarting it"
      kill "$backend_pid" 2>/dev/null || true
      sleep 2
      rm -f "$BACKEND_PID" "$BACKEND_PORT_FILE"
      backend_port=""
      backend_pid=""
    fi
  else
    rm -f "$BACKEND_PID" "$BACKEND_PORT_FILE"
  fi

  if [ -z "$backend_port" ]; then
    backend_port="$(free_port "$PREFER_BACKEND")"

    if [ ! -d "$ROOT/backend" ]; then
      echo "error: backend/ not found under $ROOT" >&2
      return 1
    fi

    (
      cd "$ROOT" || exit 1
      nohup python3 -m uvicorn backend.app:app \
        --host 127.0.0.1 --port "$backend_port" \
        >"$RUNDIR/backend.log" 2>&1 &
      echo "$!" >"$BACKEND_PID"
    )
    echo "$backend_port" >"$BACKEND_PORT_FILE"
    # Recorded so `status` can say which listing the running backend offers:
    # a narrowed demo picker should never be a mystery to whoever is looking
    # at it. The backend reads the variable itself; this only remembers it.
    echo "${SATSA_DATASET_MODE:-full}" >"$RUNDIR/dataset_mode"
    echo "backend starting on http://127.0.0.1:$backend_port"

    if ! wait_for_url "http://127.0.0.1:$backend_port/api/health"; then
      echo "error: backend did not become healthy; see $RUNDIR/backend.log" >&2
      echo "--- tail ---" >&2
      tail -20 "$RUNDIR/backend.log" >&2
      return 1
    fi
  fi

  local frontend_port=""
  local frontend_pid=""

  if frontend_pid="$(recorded_pid "$FRONTEND_PID")" && [ -f "$FRONTEND_PORT_FILE" ]; then
    frontend_port="$(cat "$FRONTEND_PORT_FILE")"

    if [ -n "$(fetch "http://127.0.0.1:$frontend_port/")" ] \
      && [ -n "$(fetch "http://127.0.0.1:$frontend_port/api/health")" ]; then
      echo "frontend already healthy: http://127.0.0.1:$frontend_port (pid $frontend_pid)"
    else
      # A stale frontend is worse than none: its /api proxy points at a
      # backend that no longer exists, which is exactly the UI's
      # "service is not responding". Rewire it to the live backend.
      echo "frontend pid $frontend_pid is stale (page or /api proxy failing) — restarting it wired to :$backend_port"
      # Kill the npm wrapper and any vite child it spawned.
      pkill -P "$frontend_pid" 2>/dev/null || true
      kill "$frontend_pid" 2>/dev/null || true
      sleep 2
      rm -f "$FRONTEND_PID" "$FRONTEND_PORT_FILE"
      frontend_port=""
      frontend_pid=""
    fi
  else
    rm -f "$FRONTEND_PID" "$FRONTEND_PORT_FILE"
  fi

  if [ -z "$frontend_port" ]; then
    frontend_port="$(free_port "$PREFER_FRONTEND")"

    if [ ! -d "$ROOT/frontend" ]; then
      echo "error: frontend/ not found under $ROOT" >&2
      return 1
    fi

    (
      cd "$ROOT/frontend" || exit 1
      SATSA_API_PORT="$backend_port" \
        nohup npm run dev -- --host 127.0.0.1 \
          --port "$frontend_port" --strictPort \
        >"$RUNDIR/frontend.log" 2>&1 &
      echo "$!" >"$FRONTEND_PID"
    )
    echo "$frontend_port" >"$FRONTEND_PORT_FILE"
    echo "frontend starting on http://127.0.0.1:$frontend_port (proxying /api to :$backend_port)"

    if ! wait_for_url "http://127.0.0.1:$frontend_port/"; then
      echo "error: frontend did not become reachable; see $RUNDIR/frontend.log" >&2
      tail -20 "$RUNDIR/frontend.log" >&2
      return 1
    fi

    if [ -z "$(fetch "http://127.0.0.1:$frontend_port/api/health")" ]; then
      echo "error: frontend is up but its /api proxy does not reach the backend" >&2
      echo "check that SATSA_API_PORT=$backend_port was honoured; see $RUNDIR/frontend.log" >&2
      return 1
    fi
  fi

  echo ""
  echo "SAT-SA is up:"
  echo "  app:      http://127.0.0.1:$(cat "$FRONTEND_PORT_FILE")"
  echo "  backend:  http://127.0.0.1:$(cat "$BACKEND_PORT_FILE")"
  echo "logs:     $RUNDIR/backend.log $RUNDIR/frontend.log"
}

# ---------------------------------------------------------------------------
# status / stop / logs
# ---------------------------------------------------------------------------

do_status() {
  local any=0
  local pid

  if pid="$(recorded_pid "$BACKEND_PID")"; then
    echo "backend   pid $pid  http://127.0.0.1:$(cat "$BACKEND_PORT_FILE" 2>/dev/null || echo '?')"
    echo "datasets  mode $(cat "$RUNDIR/dataset_mode" 2>/dev/null || echo full)"
    any=1
  fi

  if pid="$(recorded_pid "$FRONTEND_PID")"; then
    echo "frontend  pid $pid  http://127.0.0.1:$(cat "$FRONTEND_PORT_FILE" 2>/dev/null || echo '?')"
    any=1
  fi

  if [ "$any" -eq 0 ]; then
    echo "no SAT-SA dev instances running (per $RUNDIR)"
    return 1
  fi
}

do_stop() {
  local stopped=0
  local name pidfile pid

  for name in backend frontend; do
    pidfile="$RUNDIR/$name.pid"

    if [ -f "$pidfile" ] && pid="$(cat "$pidfile")" && alive "$pid"; then
      # Stop children first (vite under its npm wrapper), then the wrapper.
      pkill -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null && stopped=1
      echo "stopped $name (pid $pid)"
    fi

    rm -f "$pidfile" "$RUNDIR/$name.port" "$RUNDIR/$name.log"
  done

  if [ "$stopped" -eq 0 ]; then
    echo "nothing to stop"
  fi
}

do_logs() {
  tail -n "${2:-40}" "$RUNDIR/backend.log" "$RUNDIR/frontend.log" 2>/dev/null || echo "no logs yet in $RUNDIR"
}

# ---------------------------------------------------------------------------
# doctor — name the wiring problem behind UI service/preview errors
# ---------------------------------------------------------------------------

do_doctor() {
  local failures=0
  local warnings=0

  say_ok() { echo "  ok    $1"; };
  say_fail() { echo "  FAIL  $1"; failures=$((failures + 1)); };
  say_warn() { echo "  warn  $1"; warnings=$((warnings + 1)); };

  echo "backend:"
  local backend_pid=""
  local backend_port="$PREFER_BACKEND"

  if backend_pid="$(recorded_pid "$BACKEND_PID")"; then
    backend_port="$(cat "$BACKEND_PORT_FILE" 2>/dev/null || echo "$PREFER_BACKEND")"
    say_ok "backend process alive (pid $backend_pid, expected :$backend_port)"
  else
    say_fail "no backend process recorded — run ./dev.sh start"
  fi

  local direct
  direct="$(fetch "http://127.0.0.1:$backend_port/api/health")"

  if [ -z "$direct" ]; then
    say_fail "nothing answers GET :$backend_port/api/health — the UI cannot reach any backend there"
  else
    local summary
    summary="$(echo "$direct" | health_summary)"

    if [ "$summary" = "unreachable" ]; then
      say_fail ":$backend_port answers but not with backend health — something else holds the port"
    else
      say_ok "backend health on :$backend_port (pipeline_available=${summary%%|*}, retained=${summary##*|})"

      if [ -z "$backend_pid" ]; then
        say_warn "that backend is NOT this script's (stale pidfile or a foreign server) — ./dev.sh restart to take over cleanly"
      fi

      if [ "${summary%%|*}" != "True" ]; then
        say_warn "pipeline unavailable — analyses and previews will fail; see $RUNDIR/backend.log"
      fi
    fi
  fi

  echo "frontend:"
  local frontend_pid=""
  local frontend_port="$PREFER_FRONTEND"

  if frontend_pid="$(recorded_pid "$FRONTEND_PID")"; then
    frontend_port="$(cat "$FRONTEND_PORT_FILE" 2>/dev/null || echo "$PREFER_FRONTEND")"
    say_ok "frontend process alive (pid $frontend_pid, expected :$frontend_port)"
  else
    say_fail "no frontend process recorded — run ./dev.sh start"
  fi

  if [ -z "$(fetch "http://127.0.0.1:$frontend_port/")" ]; then
    say_fail "nothing serves the app on :$frontend_port"
  else
    say_ok "app page served on :$frontend_port"
  fi

  local proxied
  proxied="$(fetch "http://127.0.0.1:$frontend_port/api/health")"

  if [ -z "$proxied" ]; then
    say_fail "frontend's /api proxy is broken (page loads, API calls fail) — this is the UI's 'service is not responding'. Run ./dev.sh start to rewire it"
  else
    say_ok "frontend /api proxy reaches a backend"

    if [ -n "$direct" ] && [ "$direct" != "$proxied" ]; then
      # Bodies compared verbatim: same backend normally answers both
      # identically when idle; a mismatch means the proxy lands elsewhere.
      local d_retained p_retained
      d_retained="$(echo "$direct" | health_summary)"
      p_retained="$(echo "$proxied" | health_summary)"

      if [ "$d_retained" != "$p_retained" ]; then
        say_warn "proxy answers a DIFFERENT backend than :$backend_port (open the URL from ./dev.sh status, not an older tab)"
      fi
    fi
  fi

  echo "other listeners (anything SAT-SA on nearby ports):"
  local others
  others="$(ss -ltn 2>/dev/null | grep -E ':(8[0-9]{3}|51[0-9]{2}) ' || true)"

  if [ -z "$others" ]; then
    echo "  (none)"
  else
    echo "$others" | while read -r line; do echo "  $line"; done
  fi

  echo ""
  if [ "$failures" -gt 0 ]; then
    echo "doctor: $failures failing check(s), $warnings warning(s) — start with ./dev.sh start, then re-run doctor"
    return 1
  fi

  if [ "$warnings" -gt 0 ]; then
    echo "doctor: healthy but $warnings warning(s) — see above"
    return 0
  fi

  echo "doctor: all checks pass — if the UI still errors, tail the logs: ./dev.sh logs"
}

case "${1:-start}" in
  start) do_start ;;
  stop) do_stop ;;
  restart)
    do_stop
    echo ""
    do_start
    ;;
  status) do_status ;;
  doctor) do_doctor ;;
  logs) do_logs "$@" ;;
  *)
    echo "usage: ./dev.sh [start|stop|restart|status|doctor|logs]" >&2
    exit 2
    ;;
esac
