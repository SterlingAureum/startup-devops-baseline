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
contract_path = root / "delivery/contracts/demo-api.json"
schema_path = root / "delivery/contracts/release-state.schema.json"
example_path = root / "delivery/contracts/examples/demo-api-release-state.json"


class ContractError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"Missing contract file: {path.relative_to(root)}")
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"Invalid JSON in {path.relative_to(root)}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ContractError(f"Expected JSON object: {path.relative_to(root)}")
    return value


EXPECTED_ENVIRONMENTS = ["aws-dev", "aws-test", "aws-prod"]
EXPECTED_EDGES = [("aws-dev", "aws-test"), ("aws-test", "aws-prod")]
EXPECTED_PHASES = [
    "source",
    "image",
    "dev-release",
    "dev-qualification",
    "test-release",
    "test-qualification",
    "prod-approval",
    "prod-release",
    "complete",
]
EXPECTED_TRANSITIONS = list(zip(EXPECTED_PHASES, EXPECTED_PHASES[1:]))
EXPECTED_STATUSES = [
    "progressing",
    "waiting_review",
    "waiting_runtime",
    "waiting_environment",
    "blocked",
    "failed",
    "superseded",
    "completed",
]
EXPECTED_RESUME_STATUSES = {
    "waiting_review",
    "waiting_runtime",
    "waiting_environment",
    "blocked",
    "failed",
}
EXPECTED_TERMINAL_STATUSES = {"superseded", "completed"}
EXPECTED_RELEASE_TEMPLATE = "demo-api-{sourceCommit12}-{imageDigest12}"
RELEASE_ID_PATTERN = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.10.4", "Bad schemaVersion")

    application = contract.get("application")
    require(isinstance(application, dict), "application must be an object")
    require(application.get("name") == "demo-api", "Unexpected application")
    require(application.get("buildOnce") is True, "Release must build once")
    require(
        application.get("stageContract")
        == "delivery/contracts/demo-api-stages.json",
        "Reusable delivery stage contract is not linked",
    )
    require(
        application.get("orchestratorContract")
        == "delivery/contracts/demo-api-orchestrator.json",
        "Event-driven orchestrator contract is not linked",
    )
    require(
        application.get("qualificationBundleSchema")
        == "delivery/contracts/qualification-bundle.schema.json",
        "Qualification Bundle schema is not linked",
    )
    require(
        application.get("qualificationScopeContract")
        == "delivery/contracts/demo-api-qualification-scope.json",
        "Qualification scope contract is not linked",
    )
    require(
        application.get("qualificationBundleWorkflow")
        == ".github/workflows/demo-api-record-qualification-bundle.yaml",
        "Qualification Bundle workflow is not linked",
    )
    if check_files:
        for field in (
            "orchestratorContract",
            "qualificationBundleSchema",
            "qualificationScopeContract",
            "qualificationBundleWorkflow",
        ):
            require((root / application[field]).is_file(), f"Application file is missing: {field}")
    template = application.get("releaseIdTemplate")
    require(template == EXPECTED_RELEASE_TEMPLATE, "Unsafe release ID template")
    require("environment" not in template.lower(), "Release ID includes environment")
    require("workflow" not in template.lower(), "Release ID includes workflow run")
    require("runid" not in template.lower(), "Release ID includes workflow run")

    environments = contract.get("environments")
    require(isinstance(environments, list), "environments must be an array")
    names = [item.get("name") for item in environments]
    require(names == EXPECTED_ENVIRONMENTS, "Environment order must be dev/test/prod")
    orders = [item.get("order") for item in environments]
    require(orders == sorted(orders) and len(set(orders)) == 3, "Invalid environment order")

    release_files = [item.get("releaseFile") for item in environments]
    environment_files = [item.get("environmentFile") for item in environments]
    require(all(isinstance(path, str) and path for path in release_files), "Missing release file")
    require(len(set(release_files)) == 3, "Each environment needs a unique release file")
    require(len(set(environment_files)) == 3, "Each environment needs a unique environment file")

    for item in environments:
        name = item["name"]
        require(item.get("runtimeExecutor") == "trusted-runtime", f"{name}: wrong runtime executor")
        require(item.get("automaticClusterCreation") is False, f"{name}: automatic cluster creation forbidden")
        merge_policy = item.get("mergePolicy")
        require(isinstance(merge_policy, dict), f"{name}: missing merge policy")
        require(set(merge_policy) == {"reviewed", "continuous-nonprod"}, f"{name}: incomplete merge policy")
        require(merge_policy.get("reviewed") == "manual", f"{name}: reviewed mode must be manual")
        if check_files:
            require((root / item["releaseFile"]).is_file(), f"{name}: release file not found")
            require((root / item["environmentFile"]).is_file(), f"{name}: environment file not found")

    prod = environments[-1]
    require(prod.get("environmentApprovalRequired") is True, "Production Environment approval required")
    require(all(value == "manual" for value in prod["mergePolicy"].values()), "Production auto-merge forbidden")
    require(environments[0].get("automaticQualification") == "repository-variable-gated", "aws-dev qualification gate changed")
    require(environments[1].get("automaticQualification") is False, "aws-test automatic qualification enabled early")
    require(environments[2].get("automaticQualification") is False, "aws-prod automatic qualification enabled")

    promotion = contract.get("promotion")
    require(isinstance(promotion, dict), "promotion must be an object")
    edges = [(edge.get("from"), edge.get("to")) for edge in promotion.get("edges", [])]
    require(edges == EXPECTED_EDGES, "Promotion must follow aws-dev -> aws-test -> aws-prod")
    for key in ("sameDigestRequired", "releaseFileOnly", "freshQualificationEvidenceRequired"):
        require(promotion.get(key) is True, f"Promotion invariant disabled: {key}")

    policies = contract.get("executionPolicies")
    require(isinstance(policies, dict), "Missing execution policies")
    require(policies.get("default") == "reviewed", "Public default must be reviewed")
    require(policies.get("allowed") == ["reviewed", "continuous-nonprod"], "Unexpected policy set")
    require(policies.get("productionPolicyOverrideAllowed") is False, "Production policy override forbidden")

    boundaries = contract.get("executionBoundaries")
    require(isinstance(boundaries, dict), "Missing execution boundaries")
    github_hosted = boundaries.get("githubHosted", {})
    trusted_runtime = boundaries.get("trustedRuntime", {})
    require(github_hosted.get("clusterAccess") is False, "GitHub-hosted runner cannot access EKS")
    require(github_hosted.get("awsCredentials") == "none", "GitHub-hosted runner cannot receive AWS credentials")
    require(trusted_runtime.get("clusterAccess") is True, "Trusted runtime must collect cluster facts")
    require(trusted_runtime.get("credentials") == "aws-oidc-short-lived", "Trusted runtime must use short-lived OIDC credentials")
    require(trusted_runtime.get("allowedRef") == "refs/heads/main", "Trusted runtime must execute protected main")
    require(trusted_runtime.get("allowPullRequestCode") is False, "Trusted runtime cannot execute PR code")
    require(trusted_runtime.get("environmentIsolation") is True, "Runtime environments must be isolated")

    production = contract.get("productionBoundaries")
    require(isinstance(production, dict), "Missing production boundaries")
    for key in (
        "automaticMerge",
        "automaticEksCreation",
        "automaticTerraformApply",
        "automaticSecretMutation",
        "automaticDatabaseMutation",
        "automaticRollback",
    ):
        require(production.get(key) is False, f"Production boundary must remain false: {key}")
    for key in ("environmentApprovalRequired", "reviewedPullRequestRequired"):
        require(production.get(key) is True, f"Production boundary must remain true: {key}")

    model = contract.get("stateModel")
    require(isinstance(model, dict), "Missing state model")
    require(model.get("schema") == "delivery/contracts/release-state.schema.json", "Unexpected state schema")
    require(model.get("phases") == EXPECTED_PHASES, "Phase order changed or a gate was skipped")
    require(model.get("statuses") == EXPECTED_STATUSES, "Status set changed")
    require(set(model.get("resumeStatuses", [])) == EXPECTED_RESUME_STATUSES, "Resumable status set is incomplete")
    require(set(model.get("terminalStatuses", [])) == EXPECTED_TERMINAL_STATUSES, "Terminal status set changed")

    transitions = model.get("transitions")
    require(isinstance(transitions, list), "transitions must be an array")
    transition_edges = [(item.get("from"), item.get("to")) for item in transitions]
    require(transition_edges == EXPECTED_TRANSITIONS, "State transitions must be declared, ordered, and complete")
    require(all(isinstance(item.get("gate"), str) and item["gate"] for item in transitions), "Each transition needs a gate")

    reachable = {EXPECTED_PHASES[0]}
    for source, target in transition_edges:
        if source in reachable:
            reachable.add(target)
    require(EXPECTED_PHASES[-1] in reachable, "Complete phase is unreachable")

    orchestration = contract.get("orchestrationBoundaries")
    require(isinstance(orchestration, dict), "Missing orchestration boundaries")
    require(orchestration.get("longRunningWorkflow") is False, "Long-running workflow forbidden")
    require(orchestration.get("stateIsDerived") is True, "State must be derived")
    require(orchestration.get("mutableCurrentStateFile") is False, "Mutable current-state file forbidden")
    require(orchestration.get("resumeWithoutRebuild") is True, "Resume must preserve image identity")
    require(orchestration.get("environmentAbsenceIsWaiting") is True, "Absent environment must be a waiting condition")
    require(orchestration.get("awsDevQualificationVariable") == "DEMO_API_AWS_DEV_QUALIFICATION_ENABLED", "aws-dev activation variable changed")
    require(orchestration.get("automaticPromotion") is False, "Automatic Promotion enabled early")
    require(orchestration.get("automaticPullRequestMerge") is False, "Automatic PR merge enabled")


def validate_schema(contract: dict[str, Any], schema: dict[str, Any]) -> None:
    require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "Unexpected JSON Schema draft")
    require(schema.get("type") == "object", "Release state schema must describe an object")
    require(schema.get("additionalProperties") is False, "Release state must reject unknown top-level fields")
    properties = schema.get("properties", {})
    require(set(schema.get("required", [])) == set(properties), "Every state property must be required")
    require(properties.get("releaseId", {}).get("pattern") == RELEASE_ID_PATTERN.pattern, "Release ID schema pattern changed")
    require(properties.get("phase", {}).get("enum") == contract["stateModel"]["phases"], "Schema phases differ from contract")
    require(properties.get("status", {}).get("enum") == contract["stateModel"]["statuses"], "Schema statuses differ from contract")
    require(properties.get("policy", {}).get("enum") == contract["executionPolicies"]["allowed"], "Schema policies differ from contract")
    fact_environment = properties["facts"]["items"]["properties"]["environment"]["enum"]
    require(fact_environment == EXPECTED_ENVIRONMENTS, "Schema environments differ from contract")


def validate_state(contract: dict[str, Any], state: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "releaseId",
        "application",
        "identity",
        "phase",
        "status",
        "reason",
        "policy",
        "derivedAt",
        "facts",
    }
    require(set(state) == required, "State has missing or unknown top-level properties")
    require(state["schemaVersion"] == "v0.10.0", "State schema version mismatch")
    require(state["application"] == contract["application"]["name"], "State application mismatch")

    identity = state["identity"]
    identity_required = {
        "sourceRepository",
        "sourceCommit",
        "imageRepository",
        "imageDigest",
        "imageTag",
        "buildWorkflowRunId",
    }
    require(set(identity) == identity_required, "State identity is incomplete")
    require(SOURCE_COMMIT_PATTERN.fullmatch(identity["sourceCommit"]) is not None, "Invalid source commit")
    require(IMAGE_DIGEST_PATTERN.fullmatch(identity["imageDigest"]) is not None, "Invalid image digest")
    digest_hex = identity["imageDigest"].removeprefix("sha256:")
    expected_release_id = f"demo-api-{identity['sourceCommit'][:12]}-{digest_hex[:12]}"
    require(RELEASE_ID_PATTERN.fullmatch(state["releaseId"]) is not None, "Invalid release ID shape")
    require(state["releaseId"] == expected_release_id, "Release ID does not match immutable identity")
    require(state["phase"] in contract["stateModel"]["phases"], "Unknown phase")
    require(state["status"] in contract["stateModel"]["statuses"], "Unknown status")
    require(state["policy"] in contract["executionPolicies"]["allowed"], "Unknown policy")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", state["derivedAt"]) is not None, "derivedAt must be UTC")
    if state["status"] == "waiting_environment":
        require(state["reason"] == "environment-absent", "Environment wait needs environment-absent reason")

    facts = state["facts"]
    require(isinstance(facts, list) and facts, "State needs durable fact references")
    seen = set()
    for fact in facts:
        require(set(fact).issubset({"type", "environment", "ref", "sha256"}), "Unknown fact field")
        require({"type", "ref", "sha256"}.issubset(fact), "Incomplete fact reference")
        require(fact.get("environment") in EXPECTED_ENVIRONMENTS or "environment" not in fact, "Unknown fact environment")
        require(SHA256_PATTERN.fullmatch(fact["sha256"]) is not None, "Invalid fact SHA-256")
        key = (fact["type"], fact.get("environment"), fact["ref"], fact["sha256"])
        require(key not in seen, "Duplicate fact reference")
        seen.add(key)


def validate_workflow_boundary() -> None:
    workflow_dir = root / ".github/workflows"
    forbidden = re.compile(
        r"(?im)\b(kubectl|aws\s+eks|update-kubeconfig|configure-aws-credentials)\b"
    )
    for path in sorted(workflow_dir.glob("*.y*ml")):
        if path.name == "demo-api-runtime-qualification.yaml":
            continue
        require(forbidden.search(path.read_text()) is None, f"Workflow gained AWS/EKS runtime access: {path.name}")


def expect_rejected(name: str, value: dict[str, Any], validator) -> None:
    try:
        validator(value)
    except ContractError:
        return
    raise ContractError(f"Negative mutation was accepted: {name}")


contract = load_json(contract_path)
schema = load_json(schema_path)
example = load_json(example_path)

validate_contract(contract)
validate_schema(contract, schema)
validate_state(contract, example)
validate_workflow_boundary()

mutations = []

value = copy.deepcopy(contract)
value["promotion"]["edges"] = [{"from": "aws-dev", "to": "aws-prod"}]
mutations.append(("skip aws-test", value))

value = copy.deepcopy(contract)
value["environments"][2]["mergePolicy"]["continuous-nonprod"] = "automatic-after-required-checks"
mutations.append(("production auto-merge policy", value))

value = copy.deepcopy(contract)
value["productionBoundaries"]["automaticMerge"] = True
mutations.append(("production automatic merge", value))

value = copy.deepcopy(contract)
value["environments"][1]["automaticClusterCreation"] = True
mutations.append(("automatic EKS creation", value))

value = copy.deepcopy(contract)
value["application"]["releaseIdTemplate"] = "demo-api-{environment}-{sourceCommit12}-{imageDigest12}"
mutations.append(("environment in release ID", value))

value = copy.deepcopy(contract)
value["application"]["releaseIdTemplate"] = "demo-api-{sourceCommit12}-{workflowRunId}"
mutations.append(("workflow run in release ID", value))

value = copy.deepcopy(contract)
value["executionBoundaries"]["trustedRuntime"]["allowPullRequestCode"] = True
mutations.append(("PR code on trusted runtime", value))

value = copy.deepcopy(contract)
value["executionBoundaries"]["githubHosted"]["clusterAccess"] = True
mutations.append(("GitHub-hosted EKS access", value))

value = copy.deepcopy(contract)
value["environments"][2]["environmentApprovalRequired"] = False
mutations.append(("missing production Environment approval", value))

value = copy.deepcopy(contract)
value["environments"][1]["releaseFile"] = value["environments"][0]["releaseFile"]
mutations.append(("shared environment release file", value))

value = copy.deepcopy(contract)
value["stateModel"]["transitions"][3] = {
    "from": "dev-qualification",
    "to": "prod-approval",
    "gate": "unsafe-skip",
}
mutations.append(("undeclared state transition", value))

value = copy.deepcopy(contract)
value["stateModel"]["transitions"].pop()
mutations.append(("unreachable complete state", value))

for mutation_name, mutated_contract in mutations:
    expect_rejected(
        mutation_name,
        mutated_contract,
        lambda item: validate_contract(item, check_files=False),
    )

state_value = copy.deepcopy(example)
state_value["releaseId"] = "demo-api-aws-dev-04ca5ab03d99-fcfa4f473dd0"
expect_rejected("environment-specific state release ID", state_value, lambda item: validate_state(contract, item))

state_value = copy.deepcopy(example)
state_value["releaseId"] = "demo-api-04ca5ab03d99-31415926535"
expect_rejected("workflow-run state release ID", state_value, lambda item: validate_state(contract, item))

print("Release orchestration contract and negative behavior tests passed.")
PY
