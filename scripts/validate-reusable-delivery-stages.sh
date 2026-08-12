#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
from typing import Any


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/demo-api-stages.json"
application_contract_path = root / "delivery/contracts/demo-api.json"


class StageContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StageContractError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing JSON contract: {path.relative_to(root)}")
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise StageContractError(
            f"Invalid JSON in {path.relative_to(root)}: {exc}"
        ) from exc
    require(isinstance(value, dict), f"Expected object: {path.relative_to(root)}")
    return value


EXPECTED = {
    "image-publish": {
        "workflow": ".github/workflows/demo-api-image-publish.yaml",
        "entrypoints": ["push-main", "workflow-dispatch", "workflow-call"],
        "inputs": {
            "caller_ref": "string",
            "create_promotion_pr": "boolean",
            "promotion_base_branch": "string",
        },
        "outputs": [
            "image_repository",
            "image_tag",
            "image_digest",
            "metadata_artifact_name",
            "promotion_status",
            "promotion_pr_url",
        ],
        "mutationScope": [
            "ghcr-image-and-attestations",
            "optional-aws-dev-release-only-pr",
        ],
    },
    "static-qualification": {
        "workflow": ".github/workflows/demo-api-record-release-evidence.yaml",
        "entrypoints": ["workflow-dispatch", "workflow-call"],
        "inputs": {
            "environment": "string",
            "mode": "string",
            "expected_control_plane_sha": "string",
        },
        "outputs": [
            "status",
            "pr_url",
            "evidence_file",
            "image_reference",
            "base_revision",
            "artifact_name",
            "source_commit",
            "image_digest",
            "release_file_sha256",
        ],
        "allowedEnvironments": ["aws-dev", "aws-test"],
        "mutationScope": ["same-run-static-artifact", "optional-static-evidence-only-pr"],
    },
    "qualification-bundle": {
        "workflow": ".github/workflows/demo-api-record-qualification-bundle.yaml",
        "entrypoints": ["workflow-call"],
        "inputs": {
            "environment": "string",
            "release_id": "string",
            "control_plane_sha": "string",
            "static_artifact_name": "string",
            "runtime_artifact_name": "string",
        },
        "outputs": ["status", "pr_url", "bundle_file"],
        "allowedEnvironments": ["aws-dev", "aws-test"],
        "mutationScope": ["qualification-bundle-only-pr"],
    },
    "environment-promotion": {
        "workflow": ".github/workflows/demo-api-promote-environment.yaml",
        "entrypoints": ["workflow-dispatch", "workflow-call"],
        "inputs": {
            "source_environment": "string",
            "target_environment": "string",
            "qualification_mode": "string",
            "evidence_run_id": "string",
            "runtime_evidence_id": "string",
            "qualification_bundle_path": "string",
            "qualification_bundle_sha256": "string",
            "release_id": "string",
            "control_plane_sha": "string",
        },
        "outputs": [
            "status",
            "pr_url",
            "target_release_path",
            "image_tag",
            "image_digest",
            "source_commit",
        ],
        "allowedEdges": ["aws-dev->aws-test", "aws-test->aws-prod"],
        "mutationScope": ["target-release-only-pr"],
    },
    "rollback-handoff": {
        "workflow": ".github/workflows/demo-api-rollback.yaml",
        "entrypoints": ["workflow-dispatch", "workflow-call"],
        "inputs": {
            "target_environment": "string",
            "rollback_to_revision": "string",
        },
        "outputs": [
            "status",
            "pr_url",
            "target_environment",
            "target_revision",
            "image_tag",
            "image_digest",
        ],
        "allowedEnvironments": ["aws-dev", "aws-test", "aws-prod"],
        "mutationScope": ["target-release-only-pr"],
    },
}


def workflow_call_block(text: str) -> str:
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line == "  workflow_call:"),
        None,
    )
    require(start is not None, "workflow_call entrypoint is missing")
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        collected.append(line)
    return "\n".join(collected)


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.10.6", "Bad application schemaVersion")
    require(contract.get("application") == "demo-api", "Unexpected application")
    require(contract.get("defaultRef") == "refs/heads/main", "Default ref must be main")

    boundary = contract.get("executionBoundary")
    require(isinstance(boundary, dict), "Missing execution boundary")
    require(boundary.get("runner") == "github-hosted", "Stages must use GitHub-hosted execution")
    require(boundary.get("clusterAccess") is False, "Reusable stages cannot access EKS")
    require(boundary.get("awsCredentials") == "none", "Reusable stages cannot receive AWS credentials")
    require(boundary.get("automaticMerge") is False, "Reusable stages cannot merge automatically")
    require(boundary.get("automaticEnvironmentCreation") is False, "Delivery cannot create environments")

    stages = contract.get("stages")
    require(isinstance(stages, list), "stages must be an array")
    require([stage.get("id") for stage in stages] == list(EXPECTED), "Stage order or set changed")

    for stage in stages:
        stage_id = stage["id"]
        expected = EXPECTED[stage_id]
        for field in ("workflow", "entrypoints", "inputs", "outputs", "mutationScope"):
            require(stage.get(field) == expected[field], f"{stage_id}: unexpected {field}")
        for field in ("allowedEnvironments", "allowedEdges"):
            if field in expected:
                require(stage.get(field) == expected[field], f"{stage_id}: unexpected {field}")
        require(stage.get("requiresProtectedMainForOrchestration") is True, f"{stage_id}: main boundary missing")
        require(stage.get("environmentApproval") in {"not-applicable", "target-environment"}, f"{stage_id}: bad Environment binding")
        primitives = stage.get("primitiveScripts")
        require(isinstance(primitives, list) and primitives, f"{stage_id}: missing script primitives")

        if not check_files:
            continue
        workflow_path = root / stage["workflow"]
        require(workflow_path.is_file(), f"{stage_id}: workflow missing")
        workflow = workflow_path.read_text()
        call_block = workflow_call_block(workflow)
        if "workflow-dispatch" in stage["entrypoints"]:
            require("\n  workflow_dispatch:\n" in workflow, f"{stage_id}: manual compatibility entrypoint missing")
        else:
            require("\n  workflow_dispatch:\n" not in workflow, f"{stage_id}: unexpected manual entrypoint")
        require(not re.search(r"(?m)^  pull_request:\s*$", workflow), f"{stage_id}: PR code entrypoint forbidden")
        require("runs-on: ubuntu-latest" in workflow, f"{stage_id}: unexpected runner")
        require(not re.search(r"(?i)configure-aws-credentials|\baws\s+eks\b|\bkubectl\b", workflow), f"{stage_id}: AWS/EKS access forbidden")
        require("gh pr merge" not in workflow and "--auto" not in workflow, f"{stage_id}: automatic merge forbidden")

        for input_name, input_type in stage["inputs"].items():
            require(re.search(rf"(?m)^      {re.escape(input_name)}:\s*$", call_block) is not None, f"{stage_id}: missing call input {input_name}")
            require(re.search(rf"(?ms)^      {re.escape(input_name)}:\s*$.*?^        type: {re.escape(input_type)}\s*$", call_block) is not None, f"{stage_id}: wrong type for {input_name}")
        for output_name in stage["outputs"]:
            require(re.search(rf"(?m)^      {re.escape(output_name)}:\s*$", call_block) is not None, f"{stage_id}: missing call output {output_name}")

        for primitive in primitives:
            primitive_path = root / primitive
            require(primitive_path.is_file(), f"{stage_id}: primitive missing: {primitive}")
            require(primitive in workflow or primitive_path.name in workflow, f"{stage_id}: workflow does not reference {primitive}")

        if stage_id == "image-publish":
            require("inputs.caller_ref != ''" in workflow, "Image stage does not identify reusable invocation")
            require('"${CALLER_REF}" != "refs/heads/main"' in workflow, "Image stage does not validate caller_ref")
            require('"${GITHUB_REF}" != "refs/heads/main"' in workflow, "Image stage does not validate actual ref")

    promotion = next(stage for stage in stages if stage["id"] == "environment-promotion")
    rollback = next(stage for stage in stages if stage["id"] == "rollback-handoff")
    qualification = next(stage for stage in stages if stage["id"] == "static-qualification")
    require(promotion["environmentApproval"] == "target-environment", "Promotion needs target Environment")
    require(rollback["environmentApproval"] == "target-environment", "Rollback needs target Environment")
    require(qualification["environmentApproval"] == "target-environment", "Qualification needs source Environment")

    orchestration = contract.get("orchestration")
    require(isinstance(orchestration, dict), "Missing orchestrator integration")
    require(
        orchestration.get("contract") == "delivery/contracts/demo-api-orchestrator.json",
        "Unexpected orchestrator contract",
    )
    require(orchestration.get("executionMode") == "bounded-reviewed-promotion", "Unexpected execution mode")
    require(orchestration.get("stageDispatch") is True, "reviewed stage dispatch is not active")
    if check_files:
        require((root / orchestration["contract"]).is_file(), "Orchestrator contract is missing")

    deferred = contract.get("deferredStages")
    require(isinstance(deferred, dict), "Missing deferred stage declarations")
    require(deferred.get("runtimeQualification") == "v0.10.5-dispatched-aws-dev-and-aws-test", "Runtime qualification integration state changed")
    require(deferred.get("qualificationBundle") == "v0.10.5-implemented-dev-and-test", "Qualification Bundle state changed")
    require(deferred.get("productionPromotion") == "v0.10.6-reviewed-pr-preparation", "Production preparation state changed")


contract = load_json(contract_path)
application_contract = load_json(application_contract_path)
require(
    application_contract.get("application", {}).get("stageContract")
    == "delivery/contracts/demo-api-stages.json",
    "Application contract does not reference the stage contract",
)
validate_contract(contract)

mutations: list[tuple[str, Any]] = [
    ("cluster access", lambda c: c["executionBoundary"].__setitem__("clusterAccess", True)),
    ("AWS credentials", lambda c: c["executionBoundary"].__setitem__("awsCredentials", "oidc")),
    ("automatic merge", lambda c: c["executionBoundary"].__setitem__("automaticMerge", True)),
    ("automatic environment creation", lambda c: c["executionBoundary"].__setitem__("automaticEnvironmentCreation", True)),
    ("missing workflow-call", lambda c: c["stages"][0]["entrypoints"].remove("workflow-call")),
    ("PR code entrypoint", lambda c: c["stages"][1]["entrypoints"].append("pull-request")),
    ("skipped test", lambda c: c["stages"][3].__setitem__("allowedEdges", ["aws-dev->aws-prod"])),
    ("production omitted", lambda c: c["stages"][4].__setitem__("allowedEnvironments", ["aws-dev", "aws-test"])),
    ("undeclared stage", lambda c: c["stages"].append(copy.deepcopy(c["stages"][0]))),
    ("missing stage output", lambda c: c["stages"][1]["outputs"].remove("image_digest")),
    ("runtime moved to hosted", lambda c: c["deferredStages"].__setitem__("runtimeQualification", "github-hosted")),
    ("stage dispatch disabled", lambda c: c["orchestration"].__setitem__("stageDispatch", False)),
]

for name, mutate in mutations:
    candidate = copy.deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except StageContractError:
        continue
    raise SystemExit(f"Unsafe stage-contract mutation was accepted: {name}")

print("Reusable demo-api delivery stage contracts passed.")
PY
