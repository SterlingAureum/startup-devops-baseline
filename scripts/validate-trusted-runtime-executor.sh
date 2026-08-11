#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash cp jq python3 sed sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

VALIDATOR="${ROOT_DIR}/scripts/validate-trusted-runtime-executor.py"
WRITER="${ROOT_DIR}/scripts/write-demo-api-runtime-qualification.py"

echo "==> Validating trusted runtime structure"
"${VALIDATOR}" "${ROOT_DIR}"

release_file="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
source_commit="$(python3 - "${release_file}" <<'PY'
from pathlib import Path
import json, sys
section = None
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.startswith(" ") and raw.strip().endswith(":"):
        section = raw.strip()[:-1]
    elif section == "delivery" and raw.startswith("  sourceCommit:"):
        print(json.loads(raw.split(":", 1)[1].strip()))
        break
PY
)"
image_digest="$(python3 - "${release_file}" <<'PY'
from pathlib import Path
import json, sys
section = None
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.startswith(" ") and raw.strip().endswith(":"):
        section = raw.strip()[:-1]
    elif section == "image" and raw.startswith("  digest:"):
        print(json.loads(raw.split(":", 1)[1].strip()))
        break
PY
)"
release_sha="$(sha256sum "${release_file}" | awk '{print $1}')"
release_id="demo-api-${source_commit:0:12}-${image_digest#sha256:}"
release_id="${release_id:0:34}"
control_plane_sha="$(printf 'a%.0s' {1..40})"

common_arguments=(
  --environment aws-dev
  --release-id "${release_id}"
  --control-plane-sha "${control_plane_sha}"
  --expected-source-commit "${source_commit}"
  --expected-image-digest "${image_digest}"
  --expected-release-file-sha256 "${release_sha}"
  --release-file "${release_file}"
  --runner-name fixture-runner
  --workflow-run-id 12345
  --workflow-run-attempt 1
)

echo "==> Validating blocked and qualified result writing"
"${WRITER}" "${common_arguments[@]}" \
  --status blocked --reason environment_absent \
  --output "${WORK_DIR}/blocked.json" >/dev/null
jq --exit-status '
  .schemaVersion == "v0.10.3" and
  .status == "blocked" and .reason == "environment_absent" and
  .environment == "aws-dev" and
  .executor.githubEnvironment == "aws-dev-runtime" and
  (.runtime.checks | length) == 0
' "${WORK_DIR}/blocked.json" >/dev/null

jq -n \
  --arg revision "${control_plane_sha}" \
  --arg image_id "docker-pullable://ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@${image_digest}" '
  {
    argoApplication: "demo-api-aws-dev",
    argoRevision: $revision,
    workloadKind: "Deployment",
    workloadName: "demo-api",
    rolloutPhase: "not-applicable",
    analysisRunName: "",
    analysisRunPhase: "not-applicable",
    httpsHostname: "demo.dev.aureumstack.com",
    readyPodCount: 2,
    observedImageIds: [$image_id],
    checks: ["a", "b", "c", "d", "e", "f", "g", "h"]
  }
' >"${WORK_DIR}/facts.json"
"${WRITER}" "${common_arguments[@]}" \
  --status qualified --reason all_checks_passed \
  --runtime-facts "${WORK_DIR}/facts.json" \
  --aws-caller-arn arn:aws:sts::123456789012:assumed-role/runtime/fixture \
  --output "${WORK_DIR}/qualified.json" >/dev/null
jq --exit-status '
  .status == "qualified" and .reason == "all_checks_passed" and
  .runtime.readyPodCount == 2 and
  (.runtime.observedImageIds | length) == 1 and
  .controlPlane.releaseFile == "apps/demo-api/helm/values/releases/aws-dev.yaml"
' "${WORK_DIR}/qualified.json" >/dev/null

echo "==> Rejecting unsafe result identities"
if "${WRITER}" "${common_arguments[@]}" \
  --environment aws-prod --status blocked --reason environment_absent \
  --output "${WORK_DIR}/prod.json" >/dev/null 2>&1; then
  echo "Result writer accepted aws-prod." >&2
  exit 1
fi
if "${WRITER}" "${common_arguments[@]}" \
  --release-id demo-api-000000000000-000000000000 \
  --status blocked --reason environment_absent \
  --output "${WORK_DIR}/identity.json" >/dev/null 2>&1; then
  echo "Result writer accepted a mismatched Release ID." >&2
  exit 1
fi
jq '. + {token: "forbidden"}' "${WORK_DIR}/facts.json" >"${WORK_DIR}/sensitive.json"
if "${WRITER}" "${common_arguments[@]}" \
  --status qualified --reason all_checks_passed \
  --runtime-facts "${WORK_DIR}/sensitive.json" \
  --output "${WORK_DIR}/sensitive-result.json" >/dev/null 2>&1; then
  echo "Result writer accepted a sensitive artifact field." >&2
  exit 1
fi

expect_mutation_failure() {
  local name="$1"
  local mutation="$2"
  local fixture="${WORK_DIR}/mutation-${name}"
  cp -a "${ROOT_DIR}" "${fixture}"
  bash -c "${mutation}" -- "${fixture}"
  if "${fixture}/scripts/validate-trusted-runtime-executor.py" "${fixture}" >/dev/null 2>&1; then
    echo "Trusted runtime validator accepted mutation: ${name}" >&2
    exit 1
  fi
}

echo "==> Rejecting trusted runtime boundary mutations"
expect_mutation_failure github-hosted-runtime \
  'sed -i '\''s/runs-on: \[self-hosted, linux, x64, trusted-runtime, "${{ inputs.environment }}"\]/runs-on: ubuntu-latest/'\'' "$1/.github/workflows/demo-api-runtime-qualification.yaml"'
expect_mutation_failure pull-request-trigger \
  'sed -i '\''/^on:$/a\  pull_request:'\'' "$1/.github/workflows/demo-api-runtime-qualification.yaml"'
expect_mutation_failure production-runtime \
  'sed -i '\''s/          - aws-test/          - aws-test\n          - aws-prod/'\'' "$1/.github/workflows/demo-api-runtime-qualification.yaml"'
expect_mutation_failure arbitrary-cluster-input \
  'sed -i '\''/      environment:/i\      cluster_name:\n        required: true\n        type: string'\'' "$1/.github/workflows/demo-api-runtime-qualification.yaml"'
expect_mutation_failure oidc-wildcard \
  'sed -i '\''s#repo:${var.github_repository}:environment:#repo:*:environment:#'\'' "$1/infra/terraform/aws/modules/github-actions-runtime-identity/main.tf"'
expect_mutation_failure iam-write \
  'sed -i '\''s/"eks:DescribeCluster"/"eks:DescribeCluster", "eks:UpdateClusterConfig"/'\'' "$1/infra/terraform/aws/modules/github-actions-runtime-identity/main.tf"'
expect_mutation_failure rbac-write \
  'sed -i '\''0,/verbs: \["get", "list", "watch"\]/s//verbs: ["get", "list", "watch", "patch"]/'\'' "$1/clusters/aws/base/security/runtime-qualification/rbac.yaml"'
expect_mutation_failure rbac-secret \
  'sed -i '\''0,/resources: \["events", "pods", "services"\]/s//resources: ["events", "pods", "services", "secrets"]/'\'' "$1/clusters/aws/base/security/runtime-qualification/rbac.yaml"'
expect_mutation_failure production-rbac \
  'sed -i '\''/  - ..\/..\/base/a\  - ../../base/platform/runtime-qualification-rbac.yaml'\'' "$1/clusters/aws/overlays/prod/kustomization.yaml"'
expect_mutation_failure collector-terraform \
  'printf "\\nterraform apply -auto-approve\\n" >> "$1/scripts/collect-demo-api-runtime-qualification-aws.sh"'

echo "trusted runtime executor validation passed"
