#!/usr/bin/env bash
set -euo pipefail

HOSTNAME="${DEMO_API_HOST:-demo-api.local}"
BASE_URL="${DEMO_API_BASE_URL:-http://localhost}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd curl

echo "Checking ingress-nginx controller..."
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=180s

echo "Checking demo-api ingress resource..."
kubectl -n startup-apps get ingress demo-api

echo "Testing demo-api through ingress..."
echo "Using Host header: ${HOSTNAME}"

curl -fsS -H "Host: ${HOSTNAME}" "${BASE_URL}/health"
echo
curl -fsS -H "Host: ${HOSTNAME}" "${BASE_URL}/ready"
echo
curl -fsS -H "Host: ${HOSTNAME}" "${BASE_URL}/version"
echo

echo "Ingress check completed."
