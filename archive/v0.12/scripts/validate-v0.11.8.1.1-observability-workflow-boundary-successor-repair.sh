#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])

def read(relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Missing file: {relative}")
    return path.read_text()

contract_path = "delivery/contracts/v0.11.8.1.1-observability-workflow-boundary-successor-repair.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.8.1.1"
    assert value["predecessor"] == "v0.11.8.1"
    assert value["incidentEvidence"] == "info56.txt"
    assert value["failure"]["entryPoint"] == "scripts/validate-ci-quality-gates.sh"
    assert value["failure"]["validator"] == "scripts/validate-release-orchestration-contract.sh"
    assert "aws-dev-observability-qualification.yaml" in value["failure"]["message"]
    repair = value["repair"]
    assert repair["successorContractRequired"] == "delivery/contracts/v0.11.8.1-aws-dev-live-observability-qualification.json"
    assert repair["additionalReviewedWorkflow"] == "aws-dev-observability-qualification.yaml"
    assert repair["existingReviewedWorkflow"] == "demo-api-runtime-qualification.yaml"
    assert all(repair[key] is True for key in (
        "arbitraryThirdWorkflowRejected", "awsProdRejected",
        "pullRequestTriggerRejected", "kubectlApplyRejected",
        "terraformApplyRejected", "gitPushRejected",
    ))
    assert not any(value["scope"].values())

validate(contract)
assert (root / contract["repair"]["successorContractRequired"]).is_file()

historical = read("scripts/validate-release-orchestration-contract.sh")
for marker in (
    "def validate_workflow_document(",
    'allowed_runtime_workflows = {"demo-api-runtime-qualification.yaml"}',
    'allowed_runtime_workflows.add("aws-dev-observability-qualification.yaml")',
    "v0.11.8.1-aws-dev-live-observability-qualification.json",
    "unreviewed-cluster-access.yaml",
    "Unreviewed third-party AWS/EKS workflow fixture was accepted",
    "runs-on: [self-hosted, linux, x64, trusted-runtime, aws-dev]",
    "name: aws-dev-runtime",
):
    assert marker in historical, marker
for denied in ("aws-prod", "pull_request:", "kubectl apply", "terraform apply", "git push"):
    assert f'"{denied}"' in historical, denied

specialized = read("scripts/validate-v0.11.8.1-aws-dev-live-observability-qualification.sh")
assert "aws-dev-observability-qualification.yaml" in specialized
assert "runs-on: [self-hosted, linux, x64, trusted-runtime, aws-dev]" in specialized
assert "aws-prod" in specialized and "kubectl apply" in specialized

for relative, marker in (
    ("README.md", "v0.11.8.1.1-observability-workflow-boundary-successor-repair"),
    ("CHANGELOG.md", "## v0.11.8.1.1"),
    ("docs/ROADMAP.md", "v0.11.8.1.1"),
    ("docs/TROUBLESHOOTING.md", "Workflow gained AWS/EKS runtime access"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.8.1.1-observability-workflow-boundary-successor-repair.sh"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

for mutate in (
    lambda value: value["repair"].update(arbitraryThirdWorkflowRejected=False),
    lambda value: value["repair"].update(awsProdRejected=False),
    lambda value: value["scope"].update(workflowChanged=True),
    lambda value: value["scope"].update(mainMergeRequired=True),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden workflow-boundary repair mutation was accepted")

print("v0.11.8.1.1 successor allowlist, arbitrary-third-workflow rejection, and unchanged-runtime contracts passed.")
PY

"${ROOT_DIR}/scripts/validate-release-orchestration-contract.sh" >/dev/null
bash -n \
  "${ROOT_DIR}/scripts/validate-release-orchestration-contract.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.8.1.1-observability-workflow-boundary-successor-repair.sh"

echo "v0.11.8.1.1 repaired historical release-orchestration workflow boundary passed."
