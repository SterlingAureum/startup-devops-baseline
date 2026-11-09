#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY="${ROOT_DIR}/scripts/check-environment-observability-qualification-policy.sh"

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
from datetime import datetime
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

contract_path = "delivery/contracts/v0.11.8.0-environment-observability-qualification-foundation.json"
schema_path = "delivery/contracts/v0.11.8.0-environment-observability-qualification-evidence.schema.json"
contract = json.loads(read(contract_path))
schema = json.loads(read(schema_path))

environments = ["local", "aws-dev", "aws-test", "aws-prod"]
capabilities = [
    "metrics", "dashboards", "alerts", "logs", "traces", "slo",
    "progressiveDeliveryTelemetry",
]
capability_statuses = [
    "supported-verified", "supported-not-verified", "not-deployed",
    "not-applicable",
]
qualification_statuses = ["qualified", "waiting-runtime", "failed"]
allowed_actions = ["validate-identity", "observe", "collect-evidence"]
forbidden_actions = [
    "apply", "patch", "delete", "sync", "promote", "abort", "retry",
    "restart", "generate-traffic", "synthetic-alert", "fault-inject",
    "create-environment", "destroy-environment",
]

def validate_contract(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.8.0"
    assert value["predecessor"] == "v0.11.7.3.1"
    assert value["status"] == "design-and-offline-contract-implemented"
    assert list(value["environments"]) == environments
    assert value["environments"]["local"]["qualificationIncrement"] == "accepted-predecessor-evidence"
    assert value["environments"]["aws-dev"]["qualificationIncrement"] == "v0.11.8.1"
    assert value["environments"]["aws-test"]["qualificationIncrement"] == "v0.11.8.2"
    prod = value["environments"]["aws-prod"]
    assert prod["qualificationIncrement"] == "v0.11.8.3"
    assert prod["observationBoundary"] == "approval-protected-read-only"
    assert all(profile["missingRuntimeResult"] == "waiting-runtime" for profile in value["environments"].values())
    assert list(value["capabilityClasses"]) == capabilities
    assert value["capabilityClasses"]["logs"] == "profile-declared-not-inferred-from-local"
    assert value["capabilityClasses"]["traces"] == "profile-declared-not-inferred-from-local"
    assert value["capabilityStatuses"] == capability_statuses
    assert value["qualificationStatuses"] == qualification_statuses
    assert value["identityLock"]["movingRevisionAcceptedAsEvidence"] is False
    assert value["identityLock"]["crossEnvironmentEvidenceReuse"] is False
    assert value["allowedRuntimeActions"] == allowed_actions
    assert value["forbiddenRuntimeActions"] == forbidden_actions
    assert value["productionBoundary"]["approvalRequiredBeforeObservation"] is True
    assert not any(value["productionBoundary"][key] for key in (
        "kubernetesWrites", "gitWrites", "workflowDispatch", "trafficGeneration",
        "syntheticSignals", "faultInjection",
    ))
    assert value["evidence"]["waitingRuntimeIsNotQualified"] is True
    assert value["evidence"]["notDeployedIsNotVerified"] is True
    assert not any(value["scope"].values())
    assert value["deferred"] == {
        "awsDevLiveQualification": "v0.11.8.1",
        "awsTestLiveQualification": "v0.11.8.2",
        "awsProdReadOnlyQualification": "v0.11.8.3",
        "multiEnvironmentClosure": "v0.11.8.4",
        "cleanRoomReleaseAndCanaryDrills": "v0.11.9",
        "platformUpgradeRecoveryAndRtoRpo": "v0.12",
    }

validate_contract(contract)
assert contract["evidenceSchema"] == schema_path
assert (root / contract["designDocument"]).is_file()
assert (root / "delivery/contracts/v0.11.7.3.1-final-rollout-convergence-wait-repair.json").is_file()

assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert schema["additionalProperties"] is False
assert schema["properties"]["environment"]["enum"] == environments
assert schema["properties"]["status"]["enum"] == qualification_statuses
assert schema["properties"]["identity"]["properties"]["repositoryCommit"]["pattern"] == "^[0-9a-f]{40}$"
assert schema["properties"]["identity"]["properties"]["targetRevision"]["pattern"] == "^[0-9a-f]{40}$"
assert schema["$defs"]["capability"]["properties"]["status"]["enum"] == capability_statuses
assert schema["allOf"][0]["then"]["properties"]["approval"]["properties"]["approved"]["const"] is True

def iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.endswith("Z")
    except ValueError:
        return False

def validate_evidence(value: dict) -> None:
    assert set(value) == set(schema["required"])
    assert value["schemaVersion"] == "v0.11.8.0"
    assert re.fullmatch(r"v0\.11\.8\.[1-4]", value["qualificationVersion"])
    assert value["environment"] in environments
    assert value["status"] in qualification_statuses
    assert iso8601(value["observationWindow"]["startedAt"])
    assert iso8601(value["observationWindow"]["finishedAt"])
    assert value["observationWindow"]["startedAt"] <= value["observationWindow"]["finishedAt"]
    identity = value["identity"]
    assert re.fullmatch(r"[0-9a-f]{40}", identity["repositoryCommit"])
    assert re.fullmatch(r"[0-9a-f]{40}", identity["targetRevision"])
    assert identity["clusterName"] and identity["kubeContext"] and identity["applicationVersion"]
    if value["environment"].startswith("aws-"):
        assert re.fullmatch(r"[0-9]{12}", identity["awsAccountId"])
        assert re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]+", identity["awsRegion"])
    if value["environment"] == "aws-prod":
        assert value["approval"]["required"] is True
        assert value["approval"]["approved"] is True
        assert value["approval"]["reference"]
    assert list(value["capabilities"]) == capabilities
    check_ids = {item["id"] for item in value["checks"]}
    assert len(check_ids) == len(value["checks"])
    for capability in value["capabilities"].values():
        assert capability["status"] in capability_statuses
        assert set(capability["evidenceCheckIds"]) <= check_ids
        if capability["status"] == "supported-verified":
            assert capability["evidenceCheckIds"]
    if value["status"] == "qualified":
        assert all(item["outcome"] != "failed" for item in value["checks"])
        assert any(capability["status"] == "supported-verified" for capability in value["capabilities"].values())
    if value["status"] == "waiting-runtime":
        assert not any(capability["status"] == "supported-verified" for capability in value["capabilities"].values())

base_capabilities = {
    name: {"status": "supported-not-verified", "evidenceCheckIds": []}
    for name in capabilities
}
valid = {
    "schemaVersion": "v0.11.8.0",
    "qualificationVersion": "v0.11.8.1",
    "environment": "aws-dev",
    "status": "waiting-runtime",
    "observationWindow": {"startedAt": "2026-08-31T00:00:00Z", "finishedAt": "2026-08-31T00:00:01Z"},
    "identity": {
        "awsAccountId": "123456789012", "awsRegion": "ap-southeast-1",
        "clusterName": "startup-devops-baseline-dev", "kubeContext": "aws-dev",
        "repositoryCommit": "a" * 40, "targetRevision": "a" * 40,
        "applicationVersion": "v0.11.8.1-example",
    },
    "approval": {"required": False, "approved": False, "reference": None},
    "capabilities": base_capabilities,
    "checks": [{"id": "runtime.discovery", "outcome": "not-run", "observedValue": None, "diagnostic": "runtime absent"}],
}
validate_evidence(valid)

mutations = []
candidate = deepcopy(valid); candidate["status"] = "qualified"; mutations.append(candidate)
candidate = deepcopy(valid); candidate["capabilities"]["metrics"] = {"status": "supported-verified", "evidenceCheckIds": []}; mutations.append(candidate)
candidate = deepcopy(valid); candidate["identity"]["targetRevision"] = "HEAD"; mutations.append(candidate)
candidate = deepcopy(valid); candidate["environment"] = "aws-prod"; candidate["approval"] = {"required": True, "approved": False, "reference": None}; mutations.append(candidate)
candidate = deepcopy(valid); candidate["capabilities"]["traces"] = {"status": "local-verified", "evidenceCheckIds": []}; mutations.append(candidate)

for candidate in mutations:
    try:
        validate_evidence(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden environment-qualification evidence mutation was accepted")

for relative, marker in (
    ("README.md", "v0.11.8.0-environment-observability-qualification-foundation"),
    ("CHANGELOG.md", "## v0.11.8.0"),
    ("docs/OBSERVABILITY.md", "v0.11.8.0"),
    ("docs/ROADMAP.md", "v0.11.8.0"),
    ("docs/TROUBLESHOOTING.md", "waiting-runtime"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.8.0-environment-observability-qualification-foundation.sh"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", f"/{schema_path} @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

print("v0.11.8.0 environment matrix, evidence identity, status, and production read-only contracts passed.")
PY

for environment in local aws-dev aws-test; do
  for action in validate-identity observe collect-evidence; do
    output="$(QUALIFICATION_ENVIRONMENT="${environment}" QUALIFICATION_ACTION="${action}" "${POLICY}")"
    grep -Fq "policy approved ${action} for ${environment}" <<<"${output}"
  done
done

for action in validate-identity observe collect-evidence; do
  if QUALIFICATION_ENVIRONMENT=aws-prod QUALIFICATION_ACTION="${action}" "${POLICY}" >/dev/null 2>&1; then
    echo "aws-prod action passed without explicit production observation approval: ${action}" >&2
    exit 1
  fi
  APPROVED_PRODUCTION_OBSERVATION=true QUALIFICATION_ENVIRONMENT=aws-prod QUALIFICATION_ACTION="${action}" "${POLICY}" >/dev/null
done

for environment in local aws-dev aws-test aws-prod; do
  for action in apply patch delete sync promote abort retry restart generate-traffic synthetic-alert fault-inject create-environment destroy-environment; do
    if APPROVED_PRODUCTION_OBSERVATION=true QUALIFICATION_ENVIRONMENT="${environment}" QUALIFICATION_ACTION="${action}" "${POLICY}" >/dev/null 2>&1; then
      echo "Forbidden qualification action passed: ${environment}/${action}" >&2
      exit 1
    fi
  done
done

if QUALIFICATION_ENVIRONMENT=unknown QUALIFICATION_ACTION=observe "${POLICY}" >/dev/null 2>&1; then
  echo "Unknown environment passed policy validation." >&2
  exit 1
fi

bash -n "${POLICY}" "$0"
echo "v0.11.8.0 allowed-action and fail-closed mutation policy fixtures passed."
