#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])

def read(relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Missing file: {relative}")
    return path.read_text()

contract_path = "delivery/contracts/v0.11.8.1-aws-dev-live-observability-qualification.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.8.1"
    assert value["predecessor"] == "v0.11.8.0"
    assert value["status"] == "implemented-live-acceptance-required"
    assert value["environment"] == "aws-dev"
    assert value["clusterName"] == "startup-devops-baseline-dev"
    assert value["monitoringChartVersion"] == "88.5.0"
    assert value["capabilityProfile"] == {
        "metrics": "supported",
        "dashboards": "supported",
        "alerts": "supported",
        "logs": "not-deployed",
        "traces": "not-deployed",
        "slo": "supported",
        "progressiveDeliveryTelemetry": "not-applicable",
    }
    assert value["gitApplications"] == ["demo-api-aws-dev", "observability-views-aws-dev"]
    assert value["externalChartApplications"] == {"monitoring-aws-dev": "88.5.0"}
    transport = value["readTransport"]
    assert transport == {
        "namespace": "observability",
        "podPortForwardCreateAllowed": True,
        "persistentResourceCreateAllowed": False,
        "podExecAllowed": False,
        "secretReadAllowed": False,
    }
    assert value["idleTrafficPolicy"]["trafficGeneratedByQualification"] is False
    assert value["idleTrafficPolicy"]["missingRecentSliSeriesFailsControlPlaneQualification"] is False
    assert value["absencePolicy"] == {
        "environmentAbsentStatus": "waiting-runtime",
        "environmentAbsentExitCode": 2,
        "automaticEnvironmentCreation": False,
    }
    assert not any(value["scope"].values())
    assert value["deferred"] == {
        "awsTest": "v0.11.8.2",
        "awsProd": "v0.11.8.3",
        "reviewedEvidenceClosure": "v0.11.8.4",
        "trafficAndCanaryDrills": "v0.11.9",
    }

validate(contract)
assert (root / "delivery/contracts/v0.11.8.0-environment-observability-qualification-foundation.json").is_file()
for path in contract["acceptance"].values():
    if isinstance(path, str):
        assert (root / path).is_file(), path

rbac = read("clusters/aws/base/security/runtime-qualification/rbac.yaml")
role = rbac[rbac.index("name: observability-runtime-qualification"):]
for marker in (
    "namespace: observability", 'resources: ["pods/portforward"]', 'verbs: ["create"]',
    'resources: ["prometheuses", "alertmanagers", "servicemonitors", "podmonitors", "prometheusrules"]',
    'verbs: ["get", "list", "watch"]', "name: demo-api-runtime-qualification",
):
    assert marker in role, marker
assert rbac.count('resources: ["pods/portforward"]') == 1
assert rbac.count('verbs: ["create"]') == 1
for forbidden in ('resources: ["secrets"]', 'resources: ["pods/exec"]', 'verbs: ["*"]'):
    assert forbidden not in rbac, forbidden

checker = read("scripts/check-aws-dev-observability-qualification.sh")
for marker in (
    "EXPECTED_AWS_ACCOUNT_ID", "EXPECTED_CONTROL_PLANE_SHA", "EXPECTED_APPLICATION_VERSION",
    "environment_absent", "exit 2", "pods/portforward", "get secrets -n observability",
    "demo-api-aws-dev", "observability-views-aws-dev", "monitoring-aws-dev",
    'MONITORING_CHART_VERSION="${MONITORING_CHART_VERSION:-88.5.0}"',
    "demo_api:slo_availability:ratio30d", "DemoApiAvailabilityErrorBudgetFastBurn",
    "grafana_dashboard=1", "undeclared_logging_or_tracing_runtime",
    "supported-not-verified", "write_result qualified",
):
    assert marker in checker, marker
for forbidden in (
    "kubectl apply", "kubectl patch", "kubectl delete", "kubectl exec",
    "argo rollouts promote", "terraform apply", "gh workflow run", "/version",
):
    assert forbidden not in checker, forbidden

writer = read("scripts/write-environment-observability-qualification.py")
for marker in (
    '"qualificationVersion": "v0.11.8.1"', '"environment": "aws-dev"',
    '"status": "not-deployed"', '"status": "not-applicable"',
    "waiting-runtime evidence cannot contain verified capabilities",
    "reject_sensitive_values",
):
    assert marker in writer, marker

workflow = read(".github/workflows/aws-dev-observability-qualification.yaml")
for marker in (
    "workflow_dispatch:", "runs-on: [self-hosted, linux, x64, trusted-runtime, aws-dev]",
    "name: aws-dev-runtime", "id-token: write", "EXPECTED_CONTROL_PLANE_SHA",
    "check-aws-dev-observability-qualification.sh", "upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    '[[ "${status}" == "qualified" ]]',
):
    assert marker in workflow, marker
for forbidden in ("aws-prod", "terraform apply", "kubectl apply", "git push", "pull_request:"):
    assert forbidden not in workflow, forbidden

historical = read("scripts/validate-trusted-runtime-executor.py")
assert "portforward_rule" in historical
assert "persistent_rbac" in historical
assert "RBAC contains a persistent write or wildcard verb" in historical

for relative, marker in (
    ("README.md", "v0.11.8.1-aws-dev-live-observability-qualification"),
    ("CHANGELOG.md", "## v0.11.8.1"),
    ("docs/OBSERVABILITY.md", "v0.11.8.1"),
    ("docs/ROADMAP.md", "v0.11.8.1"),
    ("docs/TROUBLESHOOTING.md", "aws_dev_observability_qualified"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.8.1-aws-dev-live-observability-qualification.sh"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

for mutate in (
    lambda value: value["capabilityProfile"].update(logs="supported"),
    lambda value: value["capabilityProfile"].update(progressiveDeliveryTelemetry="supported"),
    lambda value: value["readTransport"].update(secretReadAllowed=True),
    lambda value: value["idleTrafficPolicy"].update(trafficGeneratedByQualification=True),
    lambda value: value["absencePolicy"].update(automaticEnvironmentCreation=True),
    lambda value: value["scope"].update(productionAccessAdded=True),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden aws-dev qualification mutation was accepted")

print("v0.11.8.1 aws-dev profile, RBAC, workflow, identity, evidence, and read-only contracts passed.")
PY

cat >"${WORK_DIR}/facts.json" <<'JSON'
{
  "capabilities": {
    "metrics": {"status": "supported-verified", "evidenceCheckIds": ["prometheus.ready"]},
    "dashboards": {"status": "supported-verified", "evidenceCheckIds": ["grafana.dashboard-configmaps"]},
    "alerts": {"status": "supported-verified", "evidenceCheckIds": ["alertmanager.ready"]},
    "logs": {"status": "not-deployed", "evidenceCheckIds": ["logs.absent"]},
    "traces": {"status": "not-deployed", "evidenceCheckIds": ["traces.absent"]},
    "slo": {"status": "supported-not-verified", "evidenceCheckIds": ["slo.read-only-query"]},
    "progressiveDeliveryTelemetry": {"status": "not-applicable", "evidenceCheckIds": ["demo-api.deployment"]}
  },
  "checks": [
    {"id": "prometheus.ready", "outcome": "passed"},
    {"id": "grafana.dashboard-configmaps", "outcome": "passed"},
    {"id": "alertmanager.ready", "outcome": "passed"},
    {"id": "logs.absent", "outcome": "passed"},
    {"id": "traces.absent", "outcome": "passed"},
    {"id": "slo.read-only-query", "outcome": "passed"},
    {"id": "demo-api.deployment", "outcome": "passed"}
  ]
}
JSON

"${ROOT_DIR}/scripts/write-environment-observability-qualification.py" \
  --status qualified --reason fixture \
  --started-at 2026-09-01T00:00:00Z \
  --aws-account-id 123456789012 --aws-region us-east-1 \
  --cluster-name startup-devops-baseline-dev --kube-context fixture \
  --repository-commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --target-revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --application-version v0.11.8.1-fixture \
  --runtime-facts "${WORK_DIR}/facts.json" --output "${WORK_DIR}/qualified.json" >/dev/null
jq -e '.status == "qualified" and .capabilities.logs.status == "not-deployed" and .capabilities.slo.status == "supported-not-verified"' \
  "${WORK_DIR}/qualified.json" >/dev/null

mkdir -p "${WORK_DIR}/fakebin"
cat >"${WORK_DIR}/fakebin/aws" <<'SH'
#!/usr/bin/env bash
if [[ "$*" == *"sts get-caller-identity"* ]]; then
  echo 123456789012
  exit 0
fi
if [[ "$*" == *"eks describe-cluster"* ]]; then
  echo 'ResourceNotFoundException: No cluster found' >&2
  exit 254
fi
exit 1
SH
cat >"${WORK_DIR}/fakebin/kubectl" <<'SH'
#!/usr/bin/env bash
exit 1
SH
cat >"${WORK_DIR}/fakebin/curl" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "${WORK_DIR}/fakebin/aws" "${WORK_DIR}/fakebin/kubectl" "${WORK_DIR}/fakebin/curl"

set +e
PATH="${WORK_DIR}/fakebin:${PATH}" \
EXPECTED_AWS_ACCOUNT_ID=123456789012 \
EXPECTED_CONTROL_PLANE_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)" \
EXPECTED_APPLICATION_VERSION=v0.11.8.1-fixture \
OUTPUT_FILE="${WORK_DIR}/waiting.json" \
  "${ROOT_DIR}/scripts/check-aws-dev-observability-qualification.sh" >"${WORK_DIR}/waiting.out" 2>&1
waiting_status=$?
set -e
[ "${waiting_status}" -eq 2 ]
jq -e '.status == "waiting-runtime" and .checks[0].diagnostic == "environment_absent" and ([.capabilities[].status] | index("supported-verified") | not)' \
  "${WORK_DIR}/waiting.json" >/dev/null

if "${ROOT_DIR}/scripts/write-environment-observability-qualification.py" \
  --status qualified --reason bad-fixture \
  --started-at 2026-09-01T00:00:00Z \
  --aws-account-id 123456789012 --aws-region us-east-1 \
  --cluster-name startup-devops-baseline-dev --kube-context fixture \
  --repository-commit HEAD --target-revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --application-version v0.11.8.1-fixture \
  --runtime-facts "${WORK_DIR}/facts.json" --output "${WORK_DIR}/bad.json" >/dev/null 2>&1; then
  echo "Evidence writer accepted a moving repository revision." >&2
  exit 1
fi

jq '.checks[0].diagnostic = "Bearer sensitive.fixture.token"' "${WORK_DIR}/facts.json" >"${WORK_DIR}/sensitive-facts.json"
if "${ROOT_DIR}/scripts/write-environment-observability-qualification.py" \
  --status qualified --reason bad-fixture \
  --started-at 2026-09-01T00:00:00Z \
  --aws-account-id 123456789012 --aws-region us-east-1 \
  --cluster-name startup-devops-baseline-dev --kube-context fixture \
  --repository-commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --target-revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --application-version v0.11.8.1-fixture \
  --runtime-facts "${WORK_DIR}/sensitive-facts.json" --output "${WORK_DIR}/sensitive.json" >/dev/null 2>&1; then
  echo "Evidence writer accepted sensitive runtime facts." >&2
  exit 1
fi

bash -n \
  "${ROOT_DIR}/scripts/check-aws-dev-observability-qualification.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.8.1-aws-dev-live-observability-qualification.sh"
python3 -m py_compile "${ROOT_DIR}/scripts/write-environment-observability-qualification.py"

echo "v0.11.8.1 writer, qualified evidence, waiting-runtime, and moving-revision fixtures passed."
