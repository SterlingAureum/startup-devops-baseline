#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash cmp docker git helm jq python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Checking shell script syntax"
while IFS= read -r script; do
  bash -n "${script}"
done < <(find "${ROOT_DIR}/scripts" -type f -name '*.sh' | sort)

echo "==> Validating release orchestration contracts"
"${ROOT_DIR}/scripts/validate-release-orchestration-contract.sh"

echo "==> Validating reusable delivery stage contracts"
"${ROOT_DIR}/scripts/validate-reusable-delivery-stages.sh"

echo "==> Validating event-driven release orchestrator"
"${ROOT_DIR}/scripts/validate-demo-api-release-orchestrator.sh"

echo "==> Validating unified dev/test Qualification Bundles"
"${ROOT_DIR}/scripts/validate-demo-api-qualification-bundle.sh"

echo "==> Validating trusted runtime qualification executor"
"${ROOT_DIR}/scripts/validate-trusted-runtime-executor.sh"

echo "==> Validating v0.10 final clean-room acceptance contracts"
"${ROOT_DIR}/scripts/validate-v0.10-final-acceptance.sh"

echo "==> Validating v0.11 Observability and SRE design foundation"
"${ROOT_DIR}/scripts/validate-v0.11-observability-sre-foundation.sh"

echo "==> Validating v0.11.1 metrics foundation"
"${ROOT_DIR}/scripts/validate-v0.11.1-metrics-foundation.sh"

echo "==> Validating v0.11.2 application and platform telemetry"
"${ROOT_DIR}/scripts/validate-v0.11.2-application-platform-telemetry.sh"

echo "==> Validating v0.11.3 local feature GitOps workflow"
"${ROOT_DIR}/scripts/validate-v0.11.3-local-feature-gitops.sh"

echo "==> Validating v0.11.3.1 local feature GitOps recovery guards"
"${ROOT_DIR}/scripts/validate-v0.11.3.1-local-feature-gitops-recovery.sh"

echo "==> Validating v0.11.3.2 Prometheus no-data hardening"
"${ROOT_DIR}/scripts/validate-v0.11.3.2-prometheus-no-data-hardening.sh"

echo "==> Validating v0.11.3.3 Argo CD operation race hardening"
"${ROOT_DIR}/scripts/validate-v0.11.3.3-argocd-operation-race-hardening.sh"

echo "==> Validating v0.11.3.4 unified feature revision rendering"
"${ROOT_DIR}/scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh"

echo "==> Validating v0.11.3.5 pre-merge baseline restoration"
"${ROOT_DIR}/scripts/validate-v0.11.3.5-pre-merge-baseline-restoration.sh"

echo "==> Validating v0.11.3.6 Helm migration validator coverage"
"${ROOT_DIR}/scripts/validate-v0.11.3.6-helm-migration-validator-coverage.sh"

echo "==> Validating v0.11.4.0 Grafana and recording rules"
"${ROOT_DIR}/scripts/validate-v0.11.4.0-grafana-recording-rules.sh"

echo "==> Validating v0.11.4.0.1 Helm successor coverage"
"${ROOT_DIR}/scripts/validate-v0.11.4.0.1-helm-successor-coverage.sh"

echo "==> Validating v0.11.4.1.0 controller metrics discovery"
"${ROOT_DIR}/scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh"

echo "==> Validating v0.11.4.1.0.1 acceptance stability repair"
"${ROOT_DIR}/scripts/validate-v0.11.4.1.0.1-acceptance-stability-repair.sh"

echo "==> Validating v0.11.4.1.0.2 ratio no-series repair"
"${ROOT_DIR}/scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh"

echo "==> Validating v0.11.4.1.1 operator Dashboards"
"${ROOT_DIR}/scripts/validate-v0.11.4.1.1-operator-dashboards.sh"

echo "==> Validating v0.11.4.2.0 capacity signal foundation"
"${ROOT_DIR}/scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh"

echo "==> Validating v0.11.4.2.1 Capacity and Resource Efficiency Dashboard"
"${ROOT_DIR}/scripts/validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh"

echo "==> Validating v0.11.4.2.2 replay diagnostics repair"
"${ROOT_DIR}/scripts/validate-v0.11.4.2.2-replay-diagnostics-repair.sh"

echo "==> Validating v0.11.5.0 Alertmanager foundation"
"${ROOT_DIR}/scripts/validate-v0.11.5.0-alertmanager-foundation.sh"

echo "==> Validating v0.11.5.0.1 Alertmanager matcher normalization repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.0.1-matcher-normalization-repair.sh"

echo "==> Validating v0.11.5.1 actionable alerts and Runbooks"
"${ROOT_DIR}/scripts/validate-v0.11.5.1-actionable-alerts-runbooks.sh"

echo "==> Validating v0.11.5.1.1 Prometheus target-down semantics repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.1.1-prometheus-target-down-semantics-repair.sh"

echo "==> Validating v0.11.5.1.1.1 local acceptance path repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.1.1.1-local-acceptance-path-repair.sh"

echo "==> Validating v0.11.5.2.0 alert lifecycle drill"
"${ROOT_DIR}/scripts/validate-v0.11.5.2.0-alert-lifecycle-drill.sh"

echo "==> Validating v0.11.5.2.0.1 Alertmanager webhook URL redaction repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.sh"

echo "==> Validating v0.11.5.2.0.2 alert resolution transition repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.2.0.2-alert-resolution-transition-repair.sh"

echo "==> Validating v0.11.5.2.0.3 Prometheus rule cleanup synchronization repair"
"${ROOT_DIR}/scripts/validate-v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.sh"

echo "==> Validating v0.11.6.0 centralized logging and minimal tracing foundation"
"${ROOT_DIR}/scripts/validate-v0.11.6.0-centralized-logging-minimal-tracing-foundation.sh"

echo "==> Validating v0.11.6.1.0 structured demo-api logging runtime"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh"

echo "==> Validating v0.11.6.1.1 local Loki and Alloy pod logs"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh"

echo "==> Validating v0.11.6.1.1.1 Alloy RBAC rendering and historical validator repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.sh"

echo "==> Validating v0.11.6.1.1.2 Alloy non-root and Loki rules-sidecar runtime repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.sh"

echo "==> Validating v0.11.6.1.1.5 application-scoped Alloy and Loki acceptance repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.sh"

echo "==> Validating v0.11.6.1.2 Kubernetes Events and Grafana Loki integration"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.2-kubernetes-events-grafana-loki.sh"

echo "==> Validating v0.11.6.1.2.1 Events PVC sync-wave and validation repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.sh"

echo "==> Validating v0.11.6.1.2.2 Kubernetes Event MicroTime acceptance repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.sh"

echo "==> Validating v0.11.6.1.3 local logging end-to-end closure"
"${ROOT_DIR}/scripts/validate-v0.11.6.1.3-local-logging-end-to-end-closure.sh"

echo "==> Validating v0.11.6.2.0 demo-api OpenTelemetry tracing contract"
"${ROOT_DIR}/scripts/validate-v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.sh"

echo "==> Validating v0.11.6.2.1 private local OTel Collector and Tempo runtime"
"${ROOT_DIR}/scripts/validate-v0.11.6.2.1-private-local-otel-collector-tempo-runtime.sh"

echo "==> Validating v0.11.6.2.1.1 synthetic OTLP/JSON encoding and diagnostics repair"
"${ROOT_DIR}/scripts/validate-v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.sh"

echo "==> Validating v0.11.6.2.2 real demo-api trace and log correlation"
"${ROOT_DIR}/scripts/validate-v0.11.6.2.2-real-demo-api-trace-log-correlation.sh"

echo "==> Validating security supply-chain contracts"
"${ROOT_DIR}/scripts/validate-demo-api-security-supply-chain.sh"

echo "==> Validating active GitOps repository revisions"
"${ROOT_DIR}/scripts/validate-active-gitops-revisions.sh"

echo "==> Validating AWS dev/test/prod declarations and overlays"
"${ROOT_DIR}/scripts/validate-aws-environment-declarations.sh"

echo "==> Validating cost-aware EKS control-plane logging profiles"
"${ROOT_DIR}/scripts/validate-eks-control-plane-logging-profiles.sh"

echo "==> Validating demo-api environment/release values separation"
"${ROOT_DIR}/scripts/validate-demo-api-values-separation.sh"

echo "==> Validating ordered demo-api environment promotion"
"${ROOT_DIR}/scripts/validate-demo-api-promotion.sh"

echo "==> Validating promotion evidence, approvals, and environment rollback"
"${ROOT_DIR}/scripts/validate-demo-api-promotion-governance.sh"

echo "==> Validating AWS ALB progressive-delivery declarations"
"${ROOT_DIR}/scripts/validate-demo-api-aws-progressive-delivery.sh"

echo "==> Validating demo-api AWS application-capacity scheduling"
"${ROOT_DIR}/scripts/validate-demo-api-aws-scheduling.sh"

echo "==> Validating AWS runtime evidence behavior"
"${ROOT_DIR}/scripts/validate-demo-api-runtime-evidence-behavior.sh"

echo "==> Validating v0.9 clean-room lifecycle and cleanup contracts"
"${ROOT_DIR}/scripts/validate-v0.9-lifecycle-contracts.sh"

echo "==> Validating v0.9 final evidence behavior"
"${ROOT_DIR}/scripts/validate-v0.9-final-evidence-behavior.sh"

echo "==> Validating namespace guardrail contracts"
"${ROOT_DIR}/scripts/validate-namespace-guardrails.sh"

echo "==> Validating application admission-policy contracts"
"${ROOT_DIR}/scripts/validate-application-admission-policies.sh"

echo "==> Validating EKS network-policy enforcement contracts"
"${ROOT_DIR}/scripts/validate-eks-network-policy.sh"

echo "==> Validating startup-apps NetworkPolicy contracts"
"${ROOT_DIR}/scripts/validate-startup-apps-network-policy.sh"

echo "==> Validating data-platform NetworkPolicy contracts"
"${ROOT_DIR}/scripts/validate-data-platform-network-policy.sh"

echo "==> Validating External Secrets AWS foundation contracts"
"${ROOT_DIR}/scripts/validate-external-secrets-foundation.sh"

echo "==> Validating External Secrets GitOps contracts"
"${ROOT_DIR}/scripts/validate-external-secrets-gitops.sh"

echo "==> Validating External Secrets migration contracts"
"${ROOT_DIR}/scripts/validate-external-secrets-migration.sh"

echo "==> Validating PostgreSQL credential rotation contracts"
"${ROOT_DIR}/scripts/validate-postgresql-credential-rotation.sh"

echo "==> Validating TLS, DNS, EKS endpoint, logging, and IP privacy contracts"
"${ROOT_DIR}/scripts/validate-tls-dns-security.sh"

echo "==> Validating delivery trigger contracts"
PUBLISH_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-image-publish.yaml"
ROLLBACK_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-rollback.yaml"

python3 - "${PUBLISH_WORKFLOW}" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
paths_start = lines.index("    paths:")
trigger_paths = []
for line in lines[paths_start + 1:]:
    if line.startswith("      - "):
        trigger_paths.append(line.strip().removeprefix("- ").strip("'\""))
        continue
    if line and not line.startswith("      "):
        break

if "apps/demo-api/helm/values/releases/aws-dev.yaml" in trigger_paths:
    raise SystemExit(
        "aws-dev release values must not trigger another image publish"
    )
if "apps/demo-api/src/**" not in trigger_paths:
    raise SystemExit("demo-api source changes must trigger image publishing")
if "scripts/set-demo-api-delivery-metadata.sh" not in trigger_paths:
    raise SystemExit("delivery metadata promotion changes must trigger publishing")
PY

python3 - "${ROLLBACK_WORKFLOW}" <<'PY'
from pathlib import Path
import re
import sys

workflow = Path(sys.argv[1]).read_text()
if "\n  workflow_dispatch:\n" not in workflow:
    raise SystemExit("rollback workflow must support manual dispatch")
if re.search(r"(?m)^  (push|pull_request|schedule):", workflow):
    raise SystemExit("rollback workflow must be manual-only")
if re.search(
    r"(?im)\b(kubectl|aws\s+eks|update-kubeconfig|configure-aws-credentials)\b",
    workflow,
):
    raise SystemExit("rollback workflow must not access Kubernetes or EKS")
if "target_environment:" not in workflow:
    raise SystemExit("rollback workflow must require a target environment")
for environment in ("aws-dev", "aws-test", "aws-prod"):
    if f"          - {environment}" not in workflow:
        raise SystemExit(f"rollback workflow must allow {environment}")
if "apps/demo-api/helm/values/releases/${TARGET_ENVIRONMENT}.yaml" not in workflow:
    raise SystemExit("rollback workflow must derive the environment release path")
if "name: ${{ inputs.target_environment }}" not in workflow or \
        "deployment: false" not in workflow:
    raise SystemExit("rollback workflow must use an environment approval boundary")
if "pull-requests: write" not in workflow:
    raise SystemExit("rollback workflow must prepare a reviewable pull request")
PY

echo "==> Linting and rendering the local Helm release"
helm lint "${ROOT_DIR}/apps/demo-api/helm"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/demo-api-local.yaml"

echo "==> Linting and rendering the aws-dev Helm release"
helm lint "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  >"${WORK_DIR}/demo-api-aws-dev.yaml"

for environment in aws-test aws-prod; do
  echo "==> Linting and rendering the ${environment} Helm release"
  helm lint "${ROOT_DIR}/apps/demo-api/helm" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/${environment}.yaml" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml"
  helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/${environment}.yaml" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml" \
    >"${WORK_DIR}/demo-api-${environment}.yaml"
done

TEST_IMAGE_DIGEST="sha256:$(printf 'a%.0s' {1..64})"
TEST_IMAGE_REFERENCE="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@${TEST_IMAGE_DIGEST}"

echo "==> Validating digest-pinned Helm rendering"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set "image.digest=${TEST_IMAGE_DIGEST}" \
  >"${WORK_DIR}/demo-api-local-digest.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  --set "image.digest=${TEST_IMAGE_DIGEST}" \
  >"${WORK_DIR}/demo-api-aws-dev-digest.yaml"

for manifest in \
  "${WORK_DIR}/demo-api-local-digest.yaml" \
  "${WORK_DIR}/demo-api-aws-dev-digest.yaml"; do
  grep -F "image: \"${TEST_IMAGE_REFERENCE}\"" "${manifest}" >/dev/null || {
    echo "Digest-pinned image reference is missing from ${manifest}." >&2
    exit 1
  }
done

if helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set "image.digest=sha256:invalid" \
  >"${WORK_DIR}/demo-api-invalid-digest.yaml" 2>/dev/null; then
  echo "Helm accepted an invalid image digest." >&2
  exit 1
fi

echo "==> Validating image identity metadata"
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-0123456" \
IMAGE_DIGEST="${TEST_IMAGE_DIGEST}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="0123456789abcdef0123456789abcdef01234567" \
WORKFLOW_RUN_ID="local-validation" \
OUTPUT_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  "${ROOT_DIR}/scripts/write-demo-api-image-metadata.sh"

jq --exit-status \
  --arg digest "${TEST_IMAGE_DIGEST}" \
  --arg reference "${TEST_IMAGE_REFERENCE}" \
  '
    .schemaVersion == "v0.7.1" and
    .image.digest == $digest and
    .image.reference == $reference and
    .source.commit == "0123456789abcdef0123456789abcdef01234567"
  ' "${WORK_DIR}/demo-api-image-metadata.json" >/dev/null

echo "==> Validating metadata-driven aws-dev promotion"
cp \
  "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  "${WORK_DIR}/release-aws-dev.yaml"
EXPECTED_IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
EXPECTED_SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
EXPECTED_SOURCE_COMMIT="0123456789abcdef0123456789abcdef01234567" \
METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
VALUES_FILE="${WORK_DIR}/release-aws-dev.yaml" \
  "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null

grep -F 'tag: "sha-0123456"' "${WORK_DIR}/release-aws-dev.yaml" >/dev/null
grep -F "digest: \"${TEST_IMAGE_DIGEST}\"" \
  "${WORK_DIR}/release-aws-dev.yaml" >/dev/null
grep -F 'applicationVersion: "sha-0123456"' \
  "${WORK_DIR}/release-aws-dev.yaml" >/dev/null
grep -F 'sourceRepository: "SterlingAureum/startup-devops-baseline"' \
  "${WORK_DIR}/release-aws-dev.yaml" >/dev/null
grep -F 'sourceCommit: "0123456789abcdef0123456789abcdef01234567"' \
  "${WORK_DIR}/release-aws-dev.yaml" >/dev/null
grep -F 'workflowRunId: "local-validation"' \
  "${WORK_DIR}/release-aws-dev.yaml" >/dev/null

VALUES_FILE="${WORK_DIR}/release-aws-dev.yaml" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="0123456789abcdef0123456789abcdef01234567" \
WORKFLOW_RUN_ID="local-validation" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null
if [[ "$(grep -c '^delivery:$' "${WORK_DIR}/release-aws-dev.yaml")" != "1" ]]; then
  echo "Delivery metadata update is not idempotent." >&2
  exit 1
fi

helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${WORK_DIR}/release-aws-dev.yaml" \
  >"${WORK_DIR}/demo-api-promoted-aws-dev.yaml"
grep -F "image: \"${TEST_IMAGE_REFERENCE}\"" \
  "${WORK_DIR}/demo-api-promoted-aws-dev.yaml" >/dev/null

for annotation in \
  'platform.startup.dev/image-tag: "sha-0123456"' \
  "platform.startup.dev/image-digest: \"${TEST_IMAGE_DIGEST}\"" \
  'platform.startup.dev/application-version: "sha-0123456"' \
  'platform.startup.dev/source-repository: "SterlingAureum/startup-devops-baseline"' \
  'platform.startup.dev/source-commit: "0123456789abcdef0123456789abcdef01234567"' \
  'platform.startup.dev/workflow-run-id: "local-validation"'; do
  annotation_count="$(
    grep -Fc "${annotation}" \
      "${WORK_DIR}/demo-api-promoted-aws-dev.yaml" || true
  )"
  if (( annotation_count < 2 )); then
    echo "Delivery annotation is missing from the workload or Pod template: ${annotation}" >&2
    exit 1
  fi
done

grep -F 'app.kubernetes.io/version: "sha-0123456"' \
  "${WORK_DIR}/demo-api-promoted-aws-dev.yaml" >/dev/null

if EXPECTED_SOURCE_COMMIT="ffffffffffffffffffffffffffffffffffffffff" \
  METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  VALUES_FILE="${WORK_DIR}/release-aws-dev.yaml" \
    "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null 2>&1; then
  echo "Promotion accepted metadata for an unexpected source commit." >&2
  exit 1
fi

if EXPECTED_IMAGE_REPOSITORY="ghcr.io/example/other/demo-api" \
  METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  VALUES_FILE="${WORK_DIR}/release-aws-dev.yaml" \
    "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null 2>&1; then
  echo "Promotion accepted metadata for an unexpected image repository." >&2
  exit 1
fi

echo "==> Validating history-based GitOps rollback"
ROLLBACK_REPOSITORY="${WORK_DIR}/rollback-repository"
ROLLBACK_VALUES_PATH="apps/demo-api/helm/values/releases/aws-dev.yaml"
ROLLBACK_VALUES_FILE="${ROLLBACK_REPOSITORY}/${ROLLBACK_VALUES_PATH}"
mkdir -p "$(dirname "${ROLLBACK_VALUES_FILE}")"
cp \
  "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  "${ROLLBACK_VALUES_FILE}"

git -C "${ROLLBACK_REPOSITORY}" init --quiet --initial-branch=main
git -C "${ROLLBACK_REPOSITORY}" config user.name "quality-gates"
git -C "${ROLLBACK_REPOSITORY}" config user.email "quality-gates@example.invalid"
git -C "${ROLLBACK_REPOSITORY}" add "${ROLLBACK_VALUES_PATH}"
git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "test: baseline values"
SOURCE_COMMIT_A="$(git -C "${ROLLBACK_REPOSITORY}" rev-parse HEAD)"
DIGEST_A="sha256:$(printf '1%.0s' {1..64})"

VALUES_FILE="${ROLLBACK_VALUES_FILE}" \
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-${SOURCE_COMMIT_A:0:7}" \
IMAGE_DIGEST="${DIGEST_A}" \
APP_VERSION="sha-${SOURCE_COMMIT_A:0:7}" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
VALUES_FILE="${ROLLBACK_VALUES_FILE}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="${SOURCE_COMMIT_A}" \
WORKFLOW_RUN_ID="rollback-fixture-a" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null
git -C "${ROLLBACK_REPOSITORY}" add "${ROLLBACK_VALUES_PATH}"
git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "release: fixture A"
ROLLBACK_TARGET="$(git -C "${ROLLBACK_REPOSITORY}" rev-parse HEAD)"

SOURCE_COMMIT_B="${ROLLBACK_TARGET}"
DIGEST_B="sha256:$(printf '2%.0s' {1..64})"
VALUES_FILE="${ROLLBACK_VALUES_FILE}" \
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-${SOURCE_COMMIT_B:0:7}" \
IMAGE_DIGEST="${DIGEST_B}" \
APP_VERSION="sha-${SOURCE_COMMIT_B:0:7}" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
VALUES_FILE="${ROLLBACK_VALUES_FILE}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="${SOURCE_COMMIT_B}" \
WORKFLOW_RUN_ID="rollback-fixture-b" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null
git -C "${ROLLBACK_REPOSITORY}" add "${ROLLBACK_VALUES_PATH}"
git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "release: fixture B"

REPOSITORY_DIR="${ROLLBACK_REPOSITORY}" \
ROLLBACK_TO_REVISION="${ROLLBACK_TARGET}" \
VALUES_PATH="${ROLLBACK_VALUES_PATH}" \
  "${ROOT_DIR}/scripts/prepare-demo-api-rollback.sh" >/dev/null

git -C "${ROLLBACK_REPOSITORY}" show \
  "${ROLLBACK_TARGET}:${ROLLBACK_VALUES_PATH}" |
  cmp --silent - "${ROLLBACK_VALUES_FILE}" || {
  echo "Rollback did not restore the exact historical values file." >&2
  exit 1
}

mapfile -t ROLLBACK_FILES < <(
  git -C "${ROLLBACK_REPOSITORY}" diff --name-only
)
if (( ${#ROLLBACK_FILES[@]} != 1 )) || \
   [[ "${ROLLBACK_FILES[0]}" != "${ROLLBACK_VALUES_PATH}" ]]; then
  echo "Rollback changed files outside ${ROLLBACK_VALUES_PATH}." >&2
  printf 'Rollback file: %s\n' "${ROLLBACK_FILES[@]}" >&2
  exit 1
fi

ROLLBACK_DIFF="$(
  git -C "${ROLLBACK_REPOSITORY}" diff -- "${ROLLBACK_VALUES_PATH}"
)"
REPOSITORY_DIR="${ROLLBACK_REPOSITORY}" \
ROLLBACK_TO_REVISION="${ROLLBACK_TARGET}" \
VALUES_PATH="${ROLLBACK_VALUES_PATH}" \
  "${ROOT_DIR}/scripts/prepare-demo-api-rollback.sh" >/dev/null
if [[ "$(
  git -C "${ROLLBACK_REPOSITORY}" diff -- "${ROLLBACK_VALUES_PATH}"
)" != "${ROLLBACK_DIFF}" ]]; then
  echo "Rollback preparation is not idempotent." >&2
  exit 1
fi

if REPOSITORY_DIR="${ROLLBACK_REPOSITORY}" \
  ROLLBACK_TO_REVISION="${SOURCE_COMMIT_A}" \
  VALUES_PATH="${ROLLBACK_VALUES_PATH}" \
    "${ROOT_DIR}/scripts/prepare-demo-api-rollback.sh" >/dev/null 2>&1; then
  echo "Rollback accepted a commit that is not a values-only release." >&2
  exit 1
fi

echo "==> Validating demo-api workload security"
IMAGE_NAME="demo-api-ci-test:runtime" \
  "${ROOT_DIR}/scripts/validate-demo-api-workload-security.sh"

echo "CI quality gates passed."
