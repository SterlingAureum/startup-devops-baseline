#!/usr/bin/env bash
set -euo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
ANALYSIS_TEMPLATE_NAME="${ANALYSIS_TEMPLATE_NAME:-demo-api-canary-health}"

echo "== AnalysisTemplate =="
kubectl -n "${APP_NAMESPACE}" get analysistemplate "${ANALYSIS_TEMPLATE_NAME}" -o yaml

echo
echo "== Recent AnalysisRuns =="
kubectl -n "${APP_NAMESPACE}" get analysisrun --sort-by=.metadata.creationTimestamp || true

echo
echo "== Rollout status =="
kubectl argo rollouts get rollout "${ROLLOUT_NAME}" -n "${APP_NAMESPACE}"
