#!/usr/bin/env bash
# Builds the Docker stack, checks /health, then removes everything it started.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${API_PORT:-8010}"
C=(docker compose -p text-to-sql-guardrails-smoke)
trap '"${C[@]}" down -v --rmi local >/dev/null 2>&1 || true' EXIT
API_PORT="$PORT" "${C[@]}" up -d --build --wait
curl -fsS "http://127.0.0.1:$PORT/health"
echo
QUERY_RESULT="$(curl -fsS \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT count(*) AS count FROM orders"}' \
  "http://127.0.0.1:$PORT/query")"
python -c 'import json,sys; result=json.load(sys.stdin); assert result["ok"] is True, result' \
  <<<"$QUERY_RESULT"
echo "Smoke test passed"
