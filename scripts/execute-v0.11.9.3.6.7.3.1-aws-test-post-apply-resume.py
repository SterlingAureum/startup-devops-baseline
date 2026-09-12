#!/usr/bin/env python3
"""Verify or resume read-only checks after the successful aws-test apply."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
INCIDENT_MAIN = "1376129d42c6dbc19ffb57c97244d2b31ddd4ff7"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-test"
SECRET_NAME = "startup-devops-baseline-test/demo-api/postgresql"
STATE_RELATIVE = "infra/terraform/aws/environments/test/terraform.tfstate"
RESUME_CONFIRMATION = "verify-reviewed-aws-test-post-apply-state"
SESSION_DEADLINE_UTC = "2026-09-12T17:38:53Z"
MINIMUM_REMAINING_SECONDS = 900

REPOSITORY_FINGERPRINTS = {
    "scripts/execute-v0.11.9.3.6.7.3-aws-test-terraform-apply.py": (
        "669ba4614368db656929c1a2224e6c1e73f49f5de8686e2e618b9d92429760ba"
    ),
    "delivery/contracts/v0.11.9.3.6.7.3-guarded-aws-test-terraform-apply-executor.json": (
        "c1c919ad7ce99220fa7cdb6a2398753a7c6f2d3cc90f3bf13719537a0f6ffd84"
    ),
    "scripts/check-aws-test-create-terraform-plan.py": (
        "d61a840c164a8e6a22b0ffde5f85c5b5a13de036b24530b3c98cc35002ff23c8"
    ),
}

EXPECTED_HASHES = {
    "fresh_preflight": "444ecdd6fb17bba42f48dc72083501d3cc64753aa38b8eda907d03d258f37f79",
    "private_plan": "70a3899c8475552b2bf155e287477e7f81091e3cee9cfb01deb7932e3c449be8",
    "plan_execution": "4bedd473845ec6d3b43b9b8afeeeece7c3dc5f33bf10e88d0574bbc7d18e0ec6",
    "apply_verify": "ffdc54c2c152654b63ceac050a5e951de4a2fa0bf259ba821c52440ce691b1e5",
    "failed_apply_result": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "failed_apply_stderr": "410415ad92580ecd0650655776821821caf6653bbc57cb4dd70f63995760be4e",
    "state": "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b",
}

PLAN_BUNDLE_HASHES = {
    "aws-test-create.tfplan": "7c8b5c17b17dcface9fbc97810ec1cedc1985bcb32f3157f4e476b8211d82d0e",
    "terraform-plan.json": "d93343ca8b7294537eeccff8797827c8af3a63ea6f0088a7dc101236dbf231f3",
    "terraform-plan.txt": "152bf76a977a1636706987df4210c6db085f17bc7c1aa2f2c40d87d84ee1c561",
    "plan-gate.json": "acf67d2fc1cbf81a06d92b3d774446d5c5224f9fd0069d0e377fa11dc03b6cce",
    "plan-record.json": "a196b0b7370d7c3772c3a4a60ebeff43fd39ddd59aa7921fa8afabdefab98852",
}

BEFORE_APPLY_METADATA_LOG = "secret-before-apply"
FAILED_OUTPUT_HASHES = {
    "immediate-preflight.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "immediate-preflight.stdout": "444ecdd6fb17bba42f48dc72083501d3cc64753aa38b8eda907d03d258f37f79",
    f"{BEFORE_APPLY_METADATA_LOG}.stderr": "0b434d98da1f8aae5510ee92e0e256138139ab4293b0ed566305ca1e48cca4cf",
    f"{BEFORE_APPLY_METADATA_LOG}.stdout": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "terraform-show-json-before-apply.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "terraform-show-json-before-apply.stdout": "d93343ca8b7294537eeccff8797827c8af3a63ea6f0088a7dc101236dbf231f3",
    "terraform-apply.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "terraform-apply.stdout": "ca2e3d7e1884e40a0339ce7912dae61d28be9abb720b0e3262df5e93a446e046",
    "terraform-state-list.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "terraform-state-list.stdout": "9c0c0fbce81f313a12d088bb0d071cfa20f911c1abb69fb35841de8dea7cdd96",
}

EXPECTED_UNPLANNED_DATA_TYPES = {
    "aws_caller_identity": 3,
    "aws_partition": 3,
    "aws_route53_zone": 1,
}


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_private_directory(path: Path, label: str) -> None:
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a directory")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, f"{label} mode must be 700")


def require_private_file(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 600")
    require_private_directory(path.parent, f"{label} parent")


def require_hash(path: Path, expected: str, label: str) -> None:
    require_private_file(path, label)
    require(sha256(path) == expected, f"{label} fingerprint changed")


def require_state_hash(path: Path, expected: str) -> None:
    require(path.is_file() and not path.is_symlink(), "Applied Terraform state must be regular")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "Applied Terraform state mode must be 600")
    require(sha256(path) == expected, "Applied Terraform state fingerprint changed")


def require_repository_fingerprint(root: Path, relative: str, expected: str) -> None:
    path = root / relative
    require(path.is_file() and not path.is_symlink(), "Reviewed repository input must be regular")
    require(sha256(path) == expected, f"Reviewed repository input changed: {relative}")


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"{label} is invalid") from error


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise CommandFailure("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments, cwd=ROOT, env=environment, capture_output=True, check=False, timeout=timeout
    )


def resource_base(resource: dict[str, Any]) -> str:
    module = resource.get("module")
    mode = resource.get("mode", "managed")
    resource_type = resource.get("type")
    name = resource.get("name")
    require(module is None or isinstance(module, str), "State module is invalid")
    require(mode in {"managed", "data"}, "State resource mode is invalid")
    require(isinstance(resource_type, str) and resource_type, "State resource type is invalid")
    require(isinstance(name, str) and name, "State resource name is invalid")
    prefix = f"{module}." if module else ""
    if mode == "data":
        prefix += "data."
    return f"{prefix}{resource_type}.{name}"


def classify_state(plan: Any, state: Any, state_list_bytes: bytes) -> dict[str, Any]:
    require(isinstance(plan, dict), "Plan JSON must be an object")
    changes = plan.get("resource_changes")
    require(isinstance(changes, list), "Plan resource changes are invalid")
    expected: set[str] = set()
    creates: set[str] = set()
    for change in changes:
        require(isinstance(change, dict), "Plan resource change is invalid")
        address = change.get("address")
        actions = change.get("change", {}).get("actions")
        require(isinstance(address, str) and address, "Plan resource address is invalid")
        require(isinstance(actions, list), "Plan resource actions are invalid")
        expected.add(address)
        if actions == ["create"]:
            creates.add(address)

    try:
        listed = {line for line in state_list_bytes.decode().splitlines() if line}
    except UnicodeDecodeError as error:
        raise ValueError("Captured state list is invalid") from error
    require(isinstance(state, dict) and state.get("version") == 4, "State must use version 4")
    resources = state.get("resources")
    require(isinstance(resources, list), "State resources are invalid")

    bases: list[tuple[str, str, str, int]] = []
    instance_count = 0
    for resource in resources:
        require(isinstance(resource, dict), "State resource is invalid")
        instances = resource.get("instances")
        require(isinstance(instances, list), "State instances are invalid")
        instance_count += len(instances)
        bases.append((resource_base(resource), resource.get("mode", "managed"), resource["type"], len(instances)))

    def match(address: str) -> tuple[str, str] | None:
        matches = [
            (mode, resource_type)
            for base, mode, resource_type, _ in bases
            if address == base or address.startswith(base + "[")
        ]
        require(len(matches) <= 1, "State address classification is ambiguous")
        return matches[0] if matches else None

    missing_creates = creates - listed
    unexpected = listed - expected
    unexpected_modes: Counter[str] = Counter()
    unexpected_data_types: Counter[str] = Counter()
    unclassified = 0
    for address in unexpected:
        classification = match(address)
        if classification is None:
            unclassified += 1
            continue
        mode, resource_type = classification
        unexpected_modes[mode] += 1
        if mode == "data":
            unexpected_data_types[resource_type] += 1

    classified_list_count = sum(match(address) is not None for address in listed)
    return {
        "plan_resource_change_count": len(expected),
        "plan_create_address_count": len(creates),
        "state_list_address_count": len(listed),
        "state_resource_block_count": len(resources),
        "state_resource_instance_count": instance_count,
        "classified_state_list_address_count": classified_list_count,
        "missing_planned_create_count": len(missing_creates),
        "unexpected_state_address_count": len(unexpected),
        "unexpected_managed_address_count": unexpected_modes["managed"],
        "unexpected_data_address_count": unexpected_modes["data"],
        "unexpected_unclassified_address_count": unclassified,
        "unexpected_data_type_counts": dict(sorted(unexpected_data_types.items())),
    }


def require_incident_classification(summary: dict[str, Any]) -> None:
    expected = {
        "plan_resource_change_count": 96,
        "plan_create_address_count": 90,
        "state_list_address_count": 103,
        "state_resource_block_count": 80,
        "state_resource_instance_count": 103,
        "classified_state_list_address_count": 103,
        "missing_planned_create_count": 0,
        "unexpected_state_address_count": 7,
        "unexpected_managed_address_count": 0,
        "unexpected_data_address_count": 7,
        "unexpected_unclassified_address_count": 0,
        "unexpected_data_type_counts": EXPECTED_UNPLANNED_DATA_TYPES,
    }
    require(summary == expected, "Applied state classification differs from reviewed incident evidence")


def verify_inputs(
    expected_current_main: str,
    fresh_preflight: Path,
    private_plan: Path,
    plan_execution: Path,
    apply_verify: Path,
    plan_bundle: Path,
    failed_apply_result: Path,
    failed_apply_stderr: Path,
    failed_output: Path,
    private_output: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", expected_current_main) is not None, "Expected main must be a full SHA")
    require(expected_current_main != INCIDENT_MAIN, "Resume requires the post-repair protected main")
    require(git_runner(["branch", "--show-current"]) == "main", "Resume verifier must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Resume verifier requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_current_main
        and git_runner(["rev-parse", "origin/main"]) == expected_current_main,
        "HEAD and origin/main must equal expected current main",
    )
    git_runner(["merge-base", "--is-ancestor", INCIDENT_MAIN, expected_current_main])
    for relative, expected in REPOSITORY_FINGERPRINTS.items():
        require_repository_fingerprint(repository_root, relative, expected)

    require_hash(fresh_preflight, EXPECTED_HASHES["fresh_preflight"], "Fresh preflight")
    require_hash(private_plan, EXPECTED_HASHES["private_plan"], "Private plan")
    require_hash(plan_execution, EXPECTED_HASHES["plan_execution"], "Plan execution result")
    require_hash(apply_verify, EXPECTED_HASHES["apply_verify"], "Apply verify result")
    require_hash(failed_apply_result, EXPECTED_HASHES["failed_apply_result"], "Failed apply result")
    require_hash(failed_apply_stderr, EXPECTED_HASHES["failed_apply_stderr"], "Failed apply stderr")
    require_private_directory(plan_bundle, "Plan bundle")
    for name, expected in PLAN_BUNDLE_HASHES.items():
        require_hash(plan_bundle / name, expected, f"Plan bundle {name}")
    require_private_directory(failed_output, "Failed apply output")
    require(set(path.name for path in failed_output.iterdir()) == set(FAILED_OUTPUT_HASHES), "Failed apply output inventory changed")
    for name, expected in FAILED_OUTPUT_HASHES.items():
        require_hash(failed_output / name, expected, f"Failed output {name}")

    state_path = repository_root / STATE_RELATIVE
    require_state_hash(state_path, EXPECTED_HASHES["state"])
    require_private_directory(private_output.parent, "Resume output parent")
    require(not private_output.exists() and not private_output.is_symlink(), "Resume output must be new")

    plan_doc = load_json(plan_bundle / "terraform-plan.json", "Terraform plan JSON")
    state_doc = load_json(state_path, "Terraform state")
    summary = classify_state(plan_doc, state_doc, (failed_output / "terraform-state-list.stdout").read_bytes())
    require_incident_classification(summary)

    preflight_doc = load_json(fresh_preflight, "Fresh preflight")
    private_plan_doc = load_json(private_plan, "Private plan")
    plan_execution_doc = load_json(plan_execution, "Plan execution result")
    apply_verify_doc = load_json(apply_verify, "Apply verify result")
    require(preflight_doc.get("control_plane_commit") == INCIDENT_MAIN, "Incident preflight main changed")
    require(private_plan_doc.get("planned_control_plane_commit") == INCIDENT_MAIN, "Incident private-plan main changed")
    require(plan_execution_doc.get("status") == "aws-test-create-only-terraform-plan-produced", "Plan execution status changed")
    require(apply_verify_doc.get("status") == "aws-test-terraform-apply-executor-inputs-verified", "Apply verify status changed")
    account = private_plan_doc.get("aws_account_id")
    require(isinstance(account, str) and re.fullmatch(r"[0-9]{12}", account) is not None, "Private account is invalid")
    management_cidr = f"{private_plan_doc.get('management_ipv4')}/32"

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    deadline = datetime.fromisoformat(SESSION_DEADLINE_UTC.replace("Z", "+00:00"))
    remaining = int((deadline - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "At least 900 seconds must remain in the reviewed session")
    return {
        "expected_current_main": expected_current_main,
        "account_id": account,
        "management_cidr": management_cidr,
        "release_id": private_plan_doc["candidate"]["release_id"],
        "classification": summary,
        "remaining": remaining,
    }


def safe_environment(account_id: str) -> dict[str, str]:
    allowed = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
    }
    environment = {
        key: value for key, value in os.environ.items()
        if key in allowed or key.startswith("AWS_")
    }
    for key in list(environment):
        if key.startswith("AWS_ENDPOINT_URL") or key in {"AWS_DATA_PATH", "AWS_CA_BUNDLE"}:
            del environment[key]
    environment.update(
        AWS_REGION=AWS_REGION,
        AWS_DEFAULT_REGION=AWS_REGION,
        AWS_PAGER="",
        AWS_ENVIRONMENT="aws-test",
        EXPECTED_AWS_ACCOUNT_ID=account_id,
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(content)
    path.chmod(0o600)


def logged(output: Path, label: str, arguments: list[str], environment: dict[str, str], runner: CommandRunner) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, 120)
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)
    if result.returncode:
        raise CommandFailure(f"{label} failed; preserve state and private evidence")
    return result


def execute(context: dict[str, Any], private_output: Path, runner: CommandRunner = run_command) -> dict[str, Any]:
    require(os.environ.get("AWS_ENVIRONMENT") == "aws-test", "AWS_ENVIRONMENT must be aws-test")
    require(os.environ.get("EXPECTED_AWS_ACCOUNT_ID") == context["account_id"], "Expected account must match private evidence")
    require(os.environ.get("CONFIRM_AWS_TEST_POST_APPLY_RESUME") == RESUME_CONFIRMATION, "Post-apply resume confirmation missing")
    for forbidden in (
        "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION", "CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION",
        "CONFIRM_AWS_TEST_APPLY", "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION", "CONFIRM_AWS_DEV_APPLY", "AWS_TEST_APPLY_MODE",
    ):
        require(not os.environ.get(forbidden), "Plan, apply and destroy controls must be unset")
    private_output.mkdir(mode=0o700)
    private_output.chmod(0o700)
    environment = safe_environment(context["account_id"])

    caller = logged(
        private_output, "sts-caller-identity",
        ["aws", "sts", "get-caller-identity", "--output", "json"], environment, runner,
    )
    require(json.loads(caller.stdout).get("Account") == context["account_id"], "AWS account changed")
    inventory = logged(
        private_output, "eks-list-clusters",
        ["aws", "eks", "list-clusters", "--region", AWS_REGION, "--output", "json"], environment, runner,
    )
    clusters = json.loads(inventory.stdout).get("clusters")
    require(isinstance(clusters, list) and all(isinstance(item, str) for item in clusters), "EKS inventory is invalid")
    rehearsal = set(clusters) & {
        "startup-devops-baseline-dev", CLUSTER_NAME, "startup-devops-baseline-prod"
    }
    require(rehearsal == {CLUSTER_NAME}, "Expected only the aws-test rehearsal cluster")
    described = logged(
        private_output, "eks-describe-cluster",
        ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"],
        environment, runner,
    )
    cluster = json.loads(described.stdout).get("cluster", {})
    require(cluster.get("name") == CLUSTER_NAME, "EKS cluster identity changed")
    require(cluster.get("status") == "ACTIVE", "aws-test EKS cluster is not ACTIVE")
    require(cluster.get("resourcesVpcConfig", {}).get("publicAccessCidrs") == [context["management_cidr"]], "EKS public CIDR changed")
    secret = logged(
        private_output, "secret-metadata",
        ["aws", "secretsmanager", "describe-secret", "--region", AWS_REGION, "--secret-id", SECRET_NAME, "--output", "json"],
        environment, runner,
    )
    secret_doc = json.loads(secret.stdout)
    require(secret_doc.get("Name") == SECRET_NAME and "DeletedDate" not in secret_doc, "Secret metadata is absent or pending deletion")
    summary = context["classification"]
    return {
        "status": "aws-test-post-apply-resume-verification-complete",
        "control_plane_commit": context["expected_current_main"],
        "applied_control_plane_commit": INCIDENT_MAIN,
        "candidate_release_id": context["release_id"],
        "prior_terraform_apply_succeeded": True,
        "resume_terraform_command_executed": False,
        "resume_aws_mutation_executed": False,
        "terraform_apply_reexecuted": False,
        "terraform_plan_executed": False,
        "terraform_destroy_executed": False,
        "planned_create_address_count": summary["plan_create_address_count"],
        "missing_planned_create_count": summary["missing_planned_create_count"],
        "unexpected_managed_address_count": summary["unexpected_managed_address_count"],
        "accepted_unplanned_data_address_count": summary["unexpected_data_address_count"],
        "state_address_count": summary["state_list_address_count"],
        "eks_cluster_active": True,
        "secret_metadata_present": True,
        "gitops_bootstrap_executed": False,
        "traffic_generated": False,
        "qualification_executed": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "record-aws-test-apply-and-resume-execution-evidence",
    }


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    summary = context["classification"]
    return {
        "status": "aws-test-post-apply-resume-inputs-verified",
        "control_plane_commit": context["expected_current_main"],
        "applied_control_plane_commit": INCIDENT_MAIN,
        "candidate_release_id": context["release_id"],
        "prior_terraform_apply_succeeded": True,
        "planned_create_address_count": summary["plan_create_address_count"],
        "missing_planned_create_count": summary["missing_planned_create_count"],
        "unexpected_managed_address_count": summary["unexpected_managed_address_count"],
        "accepted_unplanned_data_address_count": summary["unexpected_data_address_count"],
        "remaining_session_seconds": context["remaining"],
        "commands_executed": [],
        "resume_execution_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "terraform_destroy_authorized": False,
        "next_action": "obtain-separate-post-apply-read-only-resume-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    parser.add_argument("--fresh-preflight-result", required=True, type=Path)
    parser.add_argument("--private-plan", required=True, type=Path)
    parser.add_argument("--plan-execution-result", required=True, type=Path)
    parser.add_argument("--apply-verify-result", required=True, type=Path)
    parser.add_argument("--plan-bundle-directory", required=True, type=Path)
    parser.add_argument("--failed-apply-result", required=True, type=Path)
    parser.add_argument("--failed-apply-stderr", required=True, type=Path)
    parser.add_argument("--failed-apply-output-directory", required=True, type=Path)
    parser.add_argument("--private-output-directory", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(
            args.expected_control_plane_commit, args.fresh_preflight_result,
            args.private_plan, args.plan_execution_result, args.apply_verify_result,
            args.plan_bundle_directory, args.failed_apply_result,
            args.failed_apply_stderr, args.failed_apply_output_directory,
            args.private_output_directory,
        )
        result = redacted_verification(context) if args.phase == "verify" else execute(context, args.private_output_directory)
    except (
        CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError,
        subprocess.TimeoutExpired, ValueError,
    ) as error:
        parser.exit(1, f"aws-test post-apply resume stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
