#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="aws-test"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

NAMESPACE="${NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
WAIT_SECONDS="${WAIT_SECONDS:-1200}"

for command in aws jq kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "${CONFIRM_AWS_TEST_ROLLOUT:-}" != "promote-reviewed-aws-test" ]]; then
  echo "Set CONFIRM_AWS_TEST_ROLLOUT=promote-reviewed-aws-test after reviewing the live canary and AnalysisRun." >&2
  exit 1
fi

aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null

deadline=$((SECONDS + WAIT_SECONDS))
promotion_count=0
while true; do
  rollout_json="$(kubectl get rollout "${ROLLOUT_NAME}" -n "${NAMESPACE}" -o json)"
  phase="$(jq -r '.status.phase // ""' <<<"${rollout_json}")"
  if [[ "${phase}" == "Healthy" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the aws-test Rollout to become Healthy." >&2
    exit 1
  fi

  manual_pause="$(jq -r '
    (.status.currentStepIndex // 0) as $index |
    (.spec.strategy.canary.steps[$index].pause? // null) as $pause |
    ($pause != null and ($pause.duration? // "") == "")
  ' <<<"${rollout_json}")"
  if [[ "${manual_pause}" == "true" ]]; then
    echo "==> Live Rollout reached the explicit manual pause; promoting the reviewed step"
    kubectl argo rollouts promote "${ROLLOUT_NAME}" -n "${NAMESPACE}" >/dev/null
    promotion_count=$((promotion_count + 1))
    if (( promotion_count > 3 )); then
      echo "Unexpected number of manual pauses; refusing further promotion." >&2
      exit 1
    fi
  fi
  sleep 10
done

kubectl get application "${DEMO_APPLICATION}" -n argocd -o json |
  jq --exit-status '.status.sync.status == "Synced" and .status.health.status == "Healthy"' >/dev/null

echo "aws-test Rollout completed after ${promotion_count} reviewed manual promotion(s)."
