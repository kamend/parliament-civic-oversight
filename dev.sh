#!/usr/bin/env bash
# Run the backend (FastAPI) and the frontend (Next.js) together for development.
#
#   ./dev.sh             start both; Ctrl+C stops both
#   ./dev.sh --reload    also restart the backend when its code changes
#                        (each restart reloads the models, so it is slow)
#
# Ports can be changed from the environment:
#   BACKEND_PORT=8078 FRONTEND_PORT=3001 ./dev.sh
#
# If either server exits, the other one is stopped too.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8077}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

RELOAD=()
for arg in "$@"; do
  case "$arg" in
    --reload) RELOAD=(--reload --reload-dir parl_rag) ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# --- checks ------------------------------------------------------------------
for tool in uv pnpm; do
  command -v "$tool" >/dev/null || { echo "dev.sh: '$tool' is not installed" >&2; exit 1; }
done

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "dev.sh: port $port is already in use. Stop that process, or pick another port:" >&2
    echo "        BACKEND_PORT=... FRONTEND_PORT=... ./dev.sh" >&2
    exit 1
  fi
done

[ -f "$ROOT/backend/.env" ] || echo "dev.sh: backend/.env is missing, so /api/ask cannot generate answers (cp backend/.env.example backend/.env)"

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "dev.sh: installing frontend dependencies"
  (cd "$ROOT/frontend" && pnpm install) || exit 1
fi

# --- run ---------------------------------------------------------------------
# Job control gives each server its own process group, so stopping a group also
# stops the children that `uv run` and `pnpm` spawn.
set -m

prefix() { awk -v tag="$1" '{ print tag " " $0; fflush() }'; }

(cd "$ROOT/backend" && exec uv run uvicorn parl_rag.api.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT" ${RELOAD[@]+"${RELOAD[@]}"}) 2>&1 \
  | prefix $'\033[36m[backend] \033[0m' &
BACKEND_JOB=$!

# The frontend proxies /api/* to BACKEND_ORIGIN, so it follows BACKEND_PORT.
(cd "$ROOT/frontend" && BACKEND_ORIGIN="http://127.0.0.1:$BACKEND_PORT" FORCE_COLOR=1 \
    exec pnpm dev --port "$FRONTEND_PORT") 2>&1 \
  | prefix $'\033[35m[frontend]\033[0m' &
FRONTEND_JOB=$!

stop_group() {
  local pgid
  pgid="$(ps -o pgid= -p "$1" 2>/dev/null | tr -d ' ')"
  [ -n "$pgid" ] && kill -TERM -- "-$pgid" 2>/dev/null
}

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "dev.sh: stopping both servers"
  stop_group "$BACKEND_JOB"
  stop_group "$FRONTEND_JOB"
  wait 2>/dev/null
}
trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

echo "dev.sh: frontend http://localhost:$FRONTEND_PORT   backend http://127.0.0.1:$BACKEND_PORT (docs at /docs)"
echo "dev.sh: the backend loads its models in the background; /api/health shows models_warm"

# Wait until either server exits (polling keeps this working on bash 3.2).
while kill -0 "$BACKEND_JOB" 2>/dev/null && kill -0 "$FRONTEND_JOB" 2>/dev/null; do
  sleep 1
done
echo "dev.sh: one of the servers exited"
