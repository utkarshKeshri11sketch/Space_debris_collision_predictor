#!/usr/bin/env bash
# Start the API, hit every endpoint, validate against app/models.py, stop the server.
# Usage (from repo root or backend/): bash backend/scripts/check.sh [PORT]
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8765}"
PY="${PYTHON:-python}"

SCREENING_WARMUP=0 "$PY" -m uvicorn app.main:app --port "$PORT" --log-level warning &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT

for _ in $(seq 1 120); do
  if "$PY" -c "import httpx,sys; httpx.get('http://127.0.0.1:$PORT/api/health').raise_for_status()" 2>/dev/null; then break; fi
  sleep 0.5
done

"$PY" scripts/check_contract.py "http://127.0.0.1:$PORT"
