#!/usr/bin/env bash
set -euo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"

echo "== Rollout =="
kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o wide

echo
echo "== ReplicaSets =="
kubectl -n "${APP_NAMESPACE}" get rs -l app.kubernetes.io/name=demo-api \
  -o custom-columns='NAME:.metadata.name,DESIRED:.spec.replicas,CURRENT:.status.replicas,READY:.status.readyReplicas,AGE:.metadata.creationTimestamp'

echo
echo "== Pods by version =="
kubectl -n "${APP_NAMESPACE}" get pods -l app.kubernetes.io/name=demo-api \
  -o custom-columns='NAME:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[0].ready,HASH:.metadata.labels.rollouts-pod-template-hash,NODE:.spec.nodeName'

echo
echo "== Services selectors =="
kubectl -n "${APP_NAMESPACE}" get svc demo-api-stable demo-api-canary \
  -o jsonpath='{range .items[*]}{.metadata.name}{" -> "}{.spec.selector}{"\n"}{end}'
