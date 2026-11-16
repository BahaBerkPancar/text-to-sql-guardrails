#!/usr/bin/env bash
# Builds the Docker stack, checks /health, then removes everything it started.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${API_PORT:-8000}"
C=(docker compose -p text-to-sql-guardrails-smoke)
trap '"${C[@]}" down -v --rmi local >/dev/null 2>&1 || true' EXIT
API_PORT="$PORT" "${C[@]}" up -d --build --wait
curl -fsS "http://127.0.0.1:$PORT/health"
echo
echo "Smoke test passed"
