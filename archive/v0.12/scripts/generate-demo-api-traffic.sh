#!/usr/bin/env bash
set -euo pipefail

INGRESS_HOST="${INGRESS_HOST:-demo-api.local}"
INGRESS_BASE_URL="${INGRESS_BASE_URL:-http://localhost}"
REQUESTS="${REQUESTS:-120}"
SLEEP_SECONDS="${SLEEP_SECONDS:-0.2}"

echo "Generating ${REQUESTS} requests against ${INGRESS_BASE_URL}/version with Host=${INGRESS_HOST}"

for i in $(seq 1 "${REQUESTS}"); do
  curl -fsS -H "Host: ${INGRESS_HOST}" "${INGRESS_BASE_URL}/version" >/dev/null || true
  sleep "${SLEEP_SECONDS}"
done

echo "Done."
