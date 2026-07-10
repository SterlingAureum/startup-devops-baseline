#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"

kubectl argo rollouts abort "${ROLLOUT_NAME}" -n "${NAMESPACE}"
kubectl argo rollouts get rollout "${ROLLOUT_NAME}" -n "${NAMESPACE}"
