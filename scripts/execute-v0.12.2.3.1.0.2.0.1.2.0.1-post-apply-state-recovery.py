#!/usr/bin/env python3
"""Complete read-only evidence after the reviewed refresh-only plan was applied once."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DUAL_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"
CONFIRMATION = "complete-read-only-post-apply-refresh-state-recovery"
INCIDENT_CONTROL_PLANE_COMMIT = "b4f9f7dfee8ffecb42edf9f67d2ced55f431e0e8"
DUAL_REQUEST_SHA256 = "e2b13a02d47b5a7fa45fa723b17e99ea9b01048e8234e1949d6241d10d9f7262"
AFTER_STATE_SHA256 = "5b97b9ab595c7d072f420edf029435948135711a31b9251b7799ab3a0034b156"
AFTER_STATE_SHOW_SHA256 = "9c8dfccbe046aa41a2e88e60253d5ca58b46f0044558f19a2d5b921f0593c8bd"
APPLY_STDOUT_SHA256 = "bacf8478426de12983553575f6f5330e86cec28b03198182f4d33bf4e491d0b2"
CALLER_ADDRESS = "data.aws_caller_identity.current"

INCIDENT_ARTIFACTS = {
    "aws-identity.stdout": ("ecb9a7adbf70f2231a9da4d88e2484f3f9561b748d9dd219522dc674c0235348", 197),
    "aws-identity.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "terraform-state-pull-before.stdout": ("5ff0cb562fa7bf6d99cd2068c373646fca50f06cbaa08f3f5a3e3392bf2c55e1", 69929),
    "terraform-state-pull-before.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "terraform-state-list-before.stdout": ("099466efe2fc456d759a813278ffd8c4d0f5bf2bfb997bcea4e7c7f3dbbf73f6", 897),
    "terraform-state-list-before.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "s3-state-head-before.stdout": ("2fc54271c0bc4cc1387b8737ca67376e6beaffcf6494b378f142fe7607cb33b2", 440),
    "s3-state-head-before.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "s3-object-versions-before.stdout": ("f55d7992cb11270a12d236008ed07cd7ecde2822abd28b8cad95f4bf3ac4f1ce", 4514),
    "s3-object-versions-before.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "s3-lock-head-before.stdout": (hashlib.sha256(b"").hexdigest(), 0),
    "s3-lock-head-before.stderr": ("6b4ced3a96731d6fa121bee840a1ff6909200bfe3cd115aaef2c7f75aee03bef", 74),
    "terraform-apply-reviewed-refresh-only-plan.stdout": (APPLY_STDOUT_SHA256, 2902),
    "terraform-apply-reviewed-refresh-only-plan.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "terraform-state-pull-after.stdout": (AFTER_STATE_SHA256, 70353),
    "terraform-state-pull-after.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "terraform-state-list-after.stdout": ("099466efe2fc456d759a813278ffd8c4d0f5bf2bfb997bcea4e7c7f3dbbf73f6", 897),
    "terraform-state-list-after.stderr": (hashlib.sha256(b"").hexdigest(), 0),
    "terraform-show-state-after.stdout": (AFTER_STATE_SHOW_SHA256, 55569),
    "terraform-show-state-after.stderr": (hashlib.sha256(b"").hexdigest(), 0),
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DUAL = load_module(DUAL_PATH, "dual_form_for_post_apply_recovery")
BASE = DUAL.BASE
GitRunner = Callable[[list[str]], str]
CommandRunner = BASE.CommandRunner


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def incident_git(arguments: list[str]) -> str:
    if arguments == ["branch", "--show-current"]:
        return "main"
    if arguments == ["status", "--porcelain"]:
        return ""
    if arguments in (["rev-parse", "HEAD"], ["rev-parse", "origin/main"]):
        return INCIDENT_CONTROL_PLANE_COMMIT
    raise ValueError("Unexpected incident Git check")


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "privateDualFormRequestPath", "privateDualFormRequestSha256",
        "privateDualFormOutputDirectory", "incidentAfterStateSha256", "incidentAfterStateShowSha256",
        "incidentApplyStdoutSha256", "privateRecoveryOutputDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery-request-v1", "Recovery request schema changed")
    require(value["operation"] == CONFIRMATION, "Recovery operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateDualFormRequestPath", "privateDualFormOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["privateDualFormRequestSha256"] == DUAL_REQUEST_SHA256, "Dual-form request digest changed")
    require(value["incidentAfterStateSha256"] == AFTER_STATE_SHA256, "Incident after-state digest changed")
    require(value["incidentAfterStateShowSha256"] == AFTER_STATE_SHOW_SHA256, "Incident state-show digest changed")
    require(value["incidentApplyStdoutSha256"] == APPLY_STDOUT_SHA256, "Incident apply stdout digest changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = BASE.utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = BASE.utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=BASE.MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsIdentityAndS3Read": True, "terraformStatePullListAndShow": True,
        "postApplyEvidenceCompletion": True, "terraformInit": False,
        "terraformPlan": False, "terraformApply": False, "statePush": False,
        "destroy": False, "iamPolicyAttachment": False, "directS3Mutation": False,
        "forceUnlock": False, "automaticRetry": False, "automaticRollback": False,
    }, "Recovery execution boundary changed")
    return value


def raw_instances(state: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for resource in state.get("resources", []):
        base = f"{resource['type']}.{resource['name']}"
        if resource.get("mode") == "data":
            base = "data." + base
        if resource.get("module"):
            base = f"{resource['module']}.{base}"
        for instance in resource.get("instances", []):
            address = base
            if "index_key" in instance:
                address += "[" + json.dumps(instance["index_key"], separators=(",", ":")) + "]"
            result[address] = (resource.get("mode"), instance)
    return result


def show_resources(module: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {item["address"]: item for item in module.get("resources", [])}
    for child in module.get("child_modules", []):
        result.update(show_resources(child))
    return result


def changed_paths(left: Any, right: Any, path: str = "$") -> set[str]:
    if type(left) is not type(right):
        return {path}
    if isinstance(left, dict):
        paths: set[str] = set()
        for key in set(left) | set(right):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                paths.add(child)
            else:
                paths |= changed_paths(left[key], right[key], child)
        return paths
    if isinstance(left, list):
        paths = {path} if len(left) != len(right) else set()
        for index, (old, new) in enumerate(zip(left, right)):
            paths |= changed_paths(old, new, f"{path}[{index}]")
        return paths
    return set() if left == right else {path}


def validate_incident(context: dict[str, Any], incident_output: Path) -> dict[str, Any]:
    before = BASE.load_json(incident_output / "terraform-state-pull-before.stdout", "Incident pre-apply state")
    after = BASE.load_json(incident_output / "terraform-state-pull-after.stdout", "Incident post-apply state")
    state_show = BASE.load_json(incident_output / "terraform-show-state-after.stdout", "Incident post-apply state show")
    plan = context["plan"]
    require(before.get("version") == after.get("version") == 4 and after.get("terraform_version") == "1.14.5", "Incident state format changed")
    require(before.get("lineage") == after.get("lineage") and after.get("serial") == before.get("serial") + 1, "Incident state identity transition changed")
    managed_before, data_before = BASE.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(before)
    managed_after, data_after = BASE.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(after)
    require(managed_before == managed_after == context["managed"] and data_before == data_after == context["data"], "Incident state address inventory changed")
    require(len(managed_after) == 13 and len(data_after) == 9, "Incident state address counts changed")

    drift = {item["address"]: item for item in plan.get("resource_drift", [])}
    require(len(drift) == 7 and plan.get("resource_changes") == [], "Reviewed refresh-only plan shape changed")
    require(all(item.get("change", {}).get("actions") == ["update"] for item in drift.values()), "Reviewed drift actions changed")
    require(all(change.get("actions") == ["no-op"] for change in plan.get("output_changes", {}).values()), "Reviewed output actions changed")

    old_instances = raw_instances(before)
    new_instances = raw_instances(after)
    require(set(old_instances) == set(new_instances) and len(new_instances) == 22, "Incident instance inventory changed")
    changed = {address for address in old_instances if old_instances[address] != new_instances[address]}
    require(changed == set(drift) | {CALLER_ADDRESS}, "Incident changed-instance inventory changed")
    for address, item in drift.items():
        mode, instance = new_instances[address]
        require(mode == "managed" and instance.get("attributes") == item["change"]["after"], f"Reviewed drift after-value changed: {address}")

    old_mode, old_caller = old_instances[CALLER_ADDRESS]
    new_mode, new_caller = new_instances[CALLER_ADDRESS]
    require(old_mode == new_mode == "data", "Caller identity mode changed")
    require(changed_paths(old_caller, new_caller) == {"$.attributes.arn", "$.attributes.user_id"}, "Caller identity session projection changed outside arn/user_id")
    require(old_caller["attributes"].get("account_id") == new_caller["attributes"].get("account_id") == context["request"]["expectedAwsAccountId"], "Caller identity account changed")

    planned_root = plan.get("planned_values", {}).get("root_module", {})
    require(planned_root == {}, "Refresh-only planned root representation changed")
    persisted = state_show.get("values", {}).get("root_module", {})
    persisted_resources = show_resources(persisted)
    require(set(persisted_resources) == set(new_instances), "Persisted state-show resource inventory changed")
    require(all(persisted_resources[address].get("values") == instance[1].get("attributes") for address, instance in new_instances.items()), "Persisted state-show values do not match post-apply state")
    return {
        "before": before, "after": after, "state_show": state_show,
        "managed": managed_after, "data": data_after, "drift": drift,
    }


def exact_artifact(path: Path, label: str, digest: str, size: int) -> Path:
    artifact = BASE.require_artifact(path, label, digest)
    require(artifact.stat().st_size == size, f"{label} size changed")
    return artifact


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = BASE.require_private_file(request_path, "Private post-apply recovery request")
    require(not BASE.is_within(private_request, repository_root), "Recovery request must remain outside repository")
    request = validate_request(BASE.load_json(private_request, "Private post-apply recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = BASE.utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = BASE.utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= BASE.MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main" and git_runner(["status", "--porcelain"]) == "", "Recovery requires clean main")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    dual_request_path = BASE.require_artifact(Path(request["privateDualFormRequestPath"]), "Dual-form request", DUAL_REQUEST_SHA256)
    dual_request = DUAL.validate_request(BASE.load_json(dual_request_path, "Dual-form request"))
    require(dual_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT and dual_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Dual-form incident identity changed")
    historical_start = BASE.utc_timestamp(dual_request["approval"]["notBeforeUtc"], "Incident approval start")
    historical_expiry = BASE.utc_timestamp(dual_request["approval"]["expiresAtUtc"], "Incident approval expiry")
    context = DUAL.verify_inputs(
        dual_request_path,
        repository_root=repository_root,
        git_runner=incident_git,
        now=historical_start + (historical_expiry - historical_start) / 2,
        allow_existing_output=True,
    )
    incident_output = BASE.require_private_directory(Path(request["privateDualFormOutputDirectory"]), "Dual-form incident output")
    require(incident_output == context["output"], "Dual-form incident output path changed")
    require({item.name for item in incident_output.iterdir()} == set(INCIDENT_ARTIFACTS), "Dual-form incident artifact inventory changed")
    for name, (digest, size) in INCIDENT_ARTIFACTS.items():
        exact_artifact(incident_output / name, f"Incident artifact {name}", digest, size)
    apply_stdout = (incident_output / "terraform-apply-reviewed-refresh-only-plan.stdout").read_bytes()
    require(b"Apply complete! Resources: 0 added, 0 changed, 0 destroyed." in apply_stdout, "Incident apply success marker changed")
    incident = validate_incident(context, incident_output)

    recovery_output = BASE.require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(not BASE.is_within(recovery_output, repository_root), "Recovery output must remain outside repository")
    context.update({
        "request": request, "request_path": private_request, "output": recovery_output,
        "incident_output": incident_output, "incident": incident, "remaining": remaining,
    })
    return context


def execute(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = BASE.run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_REFRESH_ONLY_POST_APPLY_STATE_RECOVERY") == CONFIRMATION, f"Set CONFIRM_REFRESH_ONLY_POST_APPLY_STATE_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_DUAL_FORM", "CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_NORMALIZATION",
        "CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION", "CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY",
        "CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN", "CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF",
        "CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_STATE_BOOTSTRAP_MIGRATION",
        "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "All apply, plan, migration, destroy and state-push confirmations must be unset")

    output = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.PROOF_EXECUTOR.safe_environment(context["plan_request"], context["terraform_data"])
    record = BASE.PROOF_EXECUTOR.run_recorded
    identity_result = record(output, "aws-identity", ["aws", "--region", BASE.AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = BASE.PROOF_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    prefix = ["terraform", f"-chdir={context['working']}"]
    pull = record(output, "terraform-state-pull", [*prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull.returncode == 0, "Recovery state pull failed")
    current_state = json.loads(pull.stdout)
    incident_state = context["incident"]["after"]
    require({key: value for key, value in current_state.items() if key != "check_results"} == {key: value for key, value in incident_state.items() if key != "check_results"}, "Current state semantic projection changed")
    require(isinstance(current_state.get("check_results"), list) and len(current_state["check_results"]) == len(incident_state.get("check_results", [])), "Current check_results shape changed")
    managed, data = BASE.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(current_state)
    require(managed == context["managed"] and data == context["data"], "Current state address inventory changed")
    listed = record(output, "terraform-state-list", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed.returncode == 0 and BASE.MIGRATION_EXECUTOR.parse_state_list(listed.stdout) == managed | data, "Current state list changed")
    shown = record(output, "terraform-show-state", [*prefix, "show", "-json"], environment, 180, runner, repository_root)
    current_show = BASE.PROOF_EXECUTOR.parse_json_result(shown, "Current state show")
    require(current_show.get("values") == context["incident"]["state_show"].get("values"), "Current persisted state values changed")

    bucket = context["identities"]["bucket"]
    state_key = context["backend_values"]["key"]
    lock_key = state_key + ".tflock"
    head_result = record(output, "s3-state-head", ["aws", "--region", BASE.AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version = BASE.PROOF_EXECUTOR.validate_state_head(BASE.PROOF_EXECUTOR.parse_json_result(head_result, "State head"), context["identities"])
    versions_result = record(output, "s3-object-versions", ["aws", "--region", BASE.AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions = BASE.PROOF_EXECUTOR.parse_json_result(versions_result, "Object versions")
    state_versions, state_markers = BASE.PROOF_EXECUTOR.exact_history(versions, state_key)
    lock_versions, lock_markers = BASE.PROOF_EXECUTOR.exact_history(versions, lock_key)
    before_versions = BASE.load_json(context["incident_output"] / "s3-object-versions-before.stdout", "Incident pre-apply history")
    old_state_versions, old_state_markers = BASE.PROOF_EXECUTOR.exact_history(before_versions, state_key)
    old_lock_versions, old_lock_markers = BASE.PROOF_EXECUTOR.exact_history(before_versions, lock_key)
    require(len(state_versions) - len(old_state_versions) == 1 and state_markers == old_state_markers, "State object history delta changed")
    require(state_versions[0].get("VersionId") == state_version and state_versions[0].get("IsLatest") is True, "Reconciled state version is not current")
    require(len(lock_versions) - len(old_lock_versions) == 1 and len(lock_markers) - len(old_lock_markers) == 1, "Apply lock history delta changed")
    lock_result = record(output, "s3-lock-head", ["aws", "--region", BASE.AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(BASE.PROOF_EXECUTOR.is_not_found(lock_result), "Lock object remains after completed apply")

    validation = {
        "schemaVersion": "v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery-evidence-v1",
        "incidentAfterStateSha256": AFTER_STATE_SHA256,
        "currentStateSha256": hashlib.sha256(pull.stdout).hexdigest(),
        "incidentAfterStateShowSha256": AFTER_STATE_SHOW_SHA256,
        "reviewedManagedRefreshCount": 7, "callerIdentitySessionRefreshCount": 1,
        "managedAddressCount": len(managed), "dataAddressCount": len(data),
        "priorSerial": context["incident"]["before"]["serial"], "reconciledSerial": current_state["serial"],
        "stateObjectVersionDelta": 1, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "stateContentMutatedByRecovery": False, "privateObjectVersionIdsEmitted": False,
    }
    evidence_path = output / "post-apply-state-recovery-evidence.json"
    BASE.APPLY_EXECUTOR.write_private(evidence_path, BASE.canonical_json(validation))
    result = {
        "schemaVersion": "v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery-result-v1",
        "status": "refresh-only-state-reconciliation-recovered-and-read-only-validated",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": BASE.file_sha256(context["request_path"]),
        "private_dual_form_request_sha256": DUAL_REQUEST_SHA256,
        "incident_after_state_sha256": AFTER_STATE_SHA256,
        "revalidated_state_sha256": hashlib.sha256(pull.stdout).hexdigest(),
        "recovery_evidence_sha256": BASE.file_sha256(evidence_path),
        "managed_state_address_count": len(managed), "data_state_address_count": len(data),
        "reviewed_managed_refresh_count": 7, "caller_identity_session_refresh_count": 1,
        "prior_serial": context["incident"]["before"]["serial"], "reconciled_serial": current_state["serial"],
        "state_lineage_unchanged": True, "state_object_version_delta": 1,
        "state_delete_marker_delta": 0, "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "prior_saved_plan_apply_succeeded": True, "terraform_apply_reexecuted": False,
        "terraform_plan_executed": False, "terraform_init_executed": False,
        "state_push_executed": False, "destroy_executed": False,
        "iam_policy_attachment_executed": False, "direct_s3_mutation_executed": False,
        "force_unlock_executed": False, "automatic_retry_performed": False,
        "automatic_rollback_performed": False, "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "completed_at_utc": current.isoformat().replace("+00:00", "Z"),
        "next_action": "record-redacted-recovery-evidence-before-renewed-zero-change-proof",
    }
    result_path = output / "post-apply-state-recovery-result.json"
    BASE.APPLY_EXECUTOR.write_private(result_path, BASE.canonical_json(result))
    result["recovery_result_sha256"] = BASE.file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "post-apply-refresh-state-recovery-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": BASE.file_sha256(context["request_path"]),
        "private_dual_form_request_sha256": DUAL_REQUEST_SHA256,
        "incident_after_state_sha256": AFTER_STATE_SHA256,
        "incident_after_state_show_sha256": AFTER_STATE_SHOW_SHA256,
        "managed_state_address_count": len(context["managed"]),
        "data_state_address_count": len(context["data"]),
        "reviewed_managed_refresh_count": len(context["incident"]["drift"]),
        "caller_identity_session_refresh_count": 1,
        "prior_saved_plan_apply_succeeded": True,
        "recovery_execution_authorized": False, "terraform_apply_authorized": False,
        "terraform_plan_authorized": False, "state_push_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "remaining_recovery_approval_seconds": context["remaining"],
        "next_action": "obtain-separate-read-only-post-apply-state-recovery-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-recovery-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_recovery_request)) if args.phase == "verify" else execute(args.private_recovery_request)
    except (BASE.APPLY_EXECUTOR.CommandFailure, BASE.PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"Post-apply refresh state recovery stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
