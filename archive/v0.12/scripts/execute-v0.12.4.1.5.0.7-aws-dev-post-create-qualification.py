#!/usr/bin/env python3
"""Verify or execute the guarded aws-dev post-create qualification."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
CONFIRMATION = "qualify-recovered-aws-dev-for-gitops-resume"
RECOVERY_CONTROL_PLANE_COMMIT = "5d56911e2cd3510e313c2835e11667e092628482"
RECOVERY_REQUEST_SHA256 = "d20b549187fb360ac4b9ad45d0233bc1657b43b84cb0b2915e29d3ec7d552d4e"
RECOVERY_EVIDENCE_SHA256 = "e064b6ce9460e3f9e0a0d87bfc5b1622f3a18b828c9b27fb93dffac8b492d0d1"
RECOVERY_RESULT_SHA256 = "9006818a0806e5c9693c9766a2ec73c814e7038bdfa0707e2531d0a13bec18c6"
LIVE_STATE_SHA256 = "0de88b8e306055c714fdd92c2192b575055bde56e0dc7b96c2de6a0c164b7bf9"
STATE_INVENTORY_SHA256 = "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691"
NORMALIZED_CHECK_RESULTS_SHA256 = "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
NODEGROUP_NAME = "startup-devops-baseline-dev-general"
KUBERNETES_MINOR = "1.36"
EXPECTED_NODE_COUNT = 4
EXPECTED_ADDONS = {"aws-ebs-csi-driver", "coredns", "kube-proxy", "vpc-cni"}
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")


class QualificationError(ValueError):
    pass


class CommandFailure(QualificationError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise QualificationError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise QualificationError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def write_private(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)
    path.chmod(0o600)


def write_private_json(path: Path, value: Any) -> None:
    write_private(path, canonical_json(value))


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise QualificationError(f"{label} must be a valid UTC timestamp") from error
    require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def require_private_directory(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a non-symlink directory")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, f"{label} mode must be 0700")
    return path.resolve(strict=True)


def require_private_file(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 0600")
    require_private_directory(path.parent, f"{label} parent")
    return path.resolve(strict=True)


def require_new_private_directory(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(not path.exists() and not path.is_symlink(), f"{label} must be new")
    return require_private_directory(path.parent, f"{label} parent") / path.name


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedAwsRegion", "expectedClusterName",
        "privateSemanticRecoveryRequestPath", "privateSemanticRecoveryEvidencePath",
        "privateSemanticRecoveryResultPath", "privateQualificationOutputDirectory",
        "recoveryBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Qualification request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION, "AWS region changed")
    require(value["expectedClusterName"] == CLUSTER_NAME, "EKS cluster name changed")
    for key in (
        "privateSemanticRecoveryRequestPath", "privateSemanticRecoveryEvidencePath",
        "privateSemanticRecoveryResultPath", "privateQualificationOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["recoveryBoundary"] == {
        "recoveryControlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE_SHA256,
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "liveStateSha256": LIVE_STATE_SHA256,
        "stateAddressInventorySha256": STATE_INVENTORY_SHA256,
        "normalizedCheckResultsSha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "stateSerial": 9,
        "managedStateAddressCount": 90,
        "reviewedDataStateAddressCount": 6,
        "priorStateDataAddressCount": 7,
        "totalStateAddressCount": 103,
        "checkResultCount": 28,
        "checkPassStatusCount": 56,
        "semanticStateEqual": True,
        "unexplainedAddressCount": 0,
        "environmentCreated": True,
    }, "Recovery boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Qualification approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsIdentityRead": True,
        "eksClusterRead": True,
        "eksNodegroupRead": True,
        "eksAddonRead": True,
        "privateKubeconfigWrite": True,
        "kubernetesApiRead": True,
        "terraformCommand": False,
        "stateMutation": False,
        "awsMutation": False,
        "kubernetesPersistentMutation": False,
        "argocdOperation": False,
        "helmOperation": False,
        "externalSecretsPreflight": False,
        "secretValueRead": False,
        "automaticRetry": False,
        "automaticRollback": False,
        "automaticTeardown": False,
    }, "Execution boundary changed")
    return value


def validate_recovery_result(value: Any) -> None:
    require(isinstance(value, dict), "Recovery result must be an object")
    expected = {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-result-v1",
        "status": "aws-dev-saved-plan-apply-semantically-validated",
        "control_plane_commit": RECOVERY_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "recovery_evidence_sha256": RECOVERY_EVIDENCE_SHA256,
        "live_state_sha256": LIVE_STATE_SHA256,
        "state_address_inventory_sha256": STATE_INVENTORY_SHA256,
        "normalized_check_results_sha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "state_serial": 9,
        "managed_state_address_count": 90,
        "reviewed_data_state_address_count": 6,
        "prior_state_data_address_count": 7,
        "total_state_address_count": 103,
        "check_result_count": 28,
        "check_pass_status_count": 56,
        "semantic_state_equal": True,
        "unexplained_address_count": 0,
        "eks_cluster_active": True,
        "environment_created": True,
        "state_push_executed": False,
        "terraform_apply_executed_by_recovery": False,
        "terraform_init_executed": False,
        "terraform_plan_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
    }
    for key, expected_value in expected.items():
        require(value.get(key) == expected_value, f"Recovery result changed: {key}")


def validate_recovery_evidence(value: Any) -> None:
    require(isinstance(value, dict), "Recovery evidence must be an object")
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-evidence-v1", "Recovery evidence schema changed")
    require(value.get("controlPlaneCommit") == RECOVERY_CONTROL_PLANE_COMMIT, "Recovery evidence commit changed")
    require(value.get("privateRecoveryRequestSha256") == RECOVERY_REQUEST_SHA256, "Recovery evidence request changed")
    require(value.get("liveStateSha256") == LIVE_STATE_SHA256, "Recovery evidence state changed")
    require(value.get("semanticStateEqual") is True, "Recovery semantic equality is absent")
    require(value.get("totalStateAddressCount") == 103, "Recovery address count changed")
    require(value.get("terraformApplyExecutedByRecovery") is False, "Recovery unexpectedly applied Terraform")


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise QualificationError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def safe_environment(kubeconfig: Path) -> dict[str, str]:
    allowed = {"PATH", "LANG", "LC_ALL", "HOME", "AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update({"AWS_REGION": AWS_REGION, "AWS_DEFAULT_REGION": AWS_REGION, "AWS_PAGER": "", "KUBECONFIG": str(kubeconfig)})
    return environment


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private qualification request")
    require(not is_within(private_request, repository_root), "Qualification request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private qualification request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Qualification approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Qualification approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Qualification must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Qualification requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    recovery_request = require_private_file(Path(request["privateSemanticRecoveryRequestPath"]), "Semantic recovery request")
    recovery_evidence = require_private_file(Path(request["privateSemanticRecoveryEvidencePath"]), "Semantic recovery evidence")
    recovery_result = require_private_file(Path(request["privateSemanticRecoveryResultPath"]), "Semantic recovery result")
    for path in (recovery_request, recovery_evidence, recovery_result):
        require(not is_within(path, repository_root), "Semantic recovery evidence must remain outside the repository")
    require(file_sha256(recovery_request) == RECOVERY_REQUEST_SHA256, "Semantic recovery request digest changed")
    require(file_sha256(recovery_evidence) == RECOVERY_EVIDENCE_SHA256, "Semantic recovery evidence digest changed")
    require(file_sha256(recovery_result) == RECOVERY_RESULT_SHA256, "Semantic recovery result digest changed")
    validate_recovery_evidence(load_json(recovery_evidence, "Semantic recovery evidence"))
    validate_recovery_result(load_json(recovery_result, "Semantic recovery result"))

    output = require_new_private_directory(Path(request["privateQualificationOutputDirectory"]), "Private qualification output")
    require(not is_within(output, repository_root), "Qualification output must remain outside the repository")
    for path in (recovery_request, recovery_evidence.parent):
        require(not is_within(output, path) and not is_within(path, output), "Qualification output must not overlap recovery evidence")
    return {"request": request, "request_path": private_request, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-post-create-qualification-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "recovery_control_plane_commit": RECOVERY_CONTROL_PLANE_COMMIT,
        "private_qualification_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "private_recovery_evidence_sha256": RECOVERY_EVIDENCE_SHA256,
        "private_recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "semantic_state_equal": True,
        "environment_created": True,
        "total_state_address_count": 103,
        "remaining_qualification_approval_seconds": context["remaining"],
        "operational_commands_executed": [],
        "terraform_command_authorized": False,
        "aws_mutation_authorized": False,
        "kubernetes_mutation_authorized": False,
        "gitops_bootstrap_authorized": False,
        "external_secrets_preflight_authorized": False,
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-post-create-qualification-approval",
    }


def record_result(output: Path, label: str, result: subprocess.CompletedProcess[bytes]) -> None:
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)


def run_logged(output: Path, label: str, arguments: list[str], environment: dict[str, str], cwd: Path, runner: CommandRunner) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    record_result(output, label, result)
    require(result.returncode == 0, f"{label} failed")
    require(result.stderr == b"", f"{label} produced stderr")
    return result


def require_cluster(value: dict[str, Any]) -> dict[str, Any]:
    cluster = value.get("cluster")
    require(isinstance(cluster, dict), "EKS cluster response changed")
    require(cluster.get("name") == CLUSTER_NAME and cluster.get("status") == "ACTIVE", "EKS cluster is not ACTIVE")
    require(cluster.get("version") == KUBERNETES_MINOR, "EKS Kubernetes minor changed")
    access = cluster.get("resourcesVpcConfig")
    require(isinstance(access, dict) and access.get("endpointPublicAccess") is True and access.get("endpointPrivateAccess") is True, "EKS endpoint access mode changed")
    logging = cluster.get("logging", {}).get("clusterLogging")
    require(isinstance(logging, list) and all(item.get("enabled") is False for item in logging), "EKS control-plane logging profile changed")
    require(isinstance(cluster.get("endpoint"), str) and cluster["endpoint"].startswith("https://"), "EKS endpoint is invalid")
    require(isinstance(cluster.get("arn"), str) and cluster["arn"], "EKS ARN is missing")
    return cluster


def require_nodegroup(value: dict[str, Any]) -> dict[str, Any]:
    nodegroup = value.get("nodegroup")
    require(isinstance(nodegroup, dict), "EKS nodegroup response changed")
    require(nodegroup.get("clusterName") == CLUSTER_NAME and nodegroup.get("nodegroupName") == NODEGROUP_NAME, "EKS nodegroup identity changed")
    require(nodegroup.get("status") == "ACTIVE" and nodegroup.get("version") == KUBERNETES_MINOR, "EKS nodegroup is not ACTIVE on the reviewed minor")
    require(nodegroup.get("capacityType") == "ON_DEMAND" and nodegroup.get("instanceTypes") == ["t3.medium"], "EKS nodegroup capacity changed")
    require(nodegroup.get("labels", {}).get("workload") == "system", "EKS nodegroup workload label changed")
    require(nodegroup.get("scalingConfig") == {"minSize": 4, "maxSize": 4, "desiredSize": 4}, "EKS nodegroup scaling changed")
    require(nodegroup.get("health", {}).get("issues") == [], "EKS nodegroup reports health issues")
    return nodegroup


def require_nodes(value: dict[str, Any]) -> None:
    items = value.get("items")
    require(isinstance(items, list) and len(items) == EXPECTED_NODE_COUNT, "Kubernetes node count changed")
    for node in items:
        require(isinstance(node, dict), "Kubernetes node entry changed")
        metadata = node.get("metadata", {})
        labels = metadata.get("labels", {})
        require(labels.get("workload") == "system" and labels.get("eks.amazonaws.com/nodegroup") == NODEGROUP_NAME, "Kubernetes node labels changed")
        require(node.get("spec", {}).get("unschedulable") is not True, "Kubernetes node is unschedulable")
        conditions = node.get("status", {}).get("conditions", [])
        require(any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions), "Kubernetes node is not Ready")
        kubelet = node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion")
        require(isinstance(kubelet, str) and kubelet.startswith(f"v{KUBERNETES_MINOR}."), "Kubelet minor changed")


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_POST_CREATE_QUALIFICATION") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_POST_CREATE_QUALIFICATION={CONFIRMATION}")
    forbidden = (
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
        "CONFIRM_STATE_MIGRATION", "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP",
        "CONFIRM_AWS_DEV_ROOT_APPLICATION_DEPLOY", "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
        "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN", "CONFIRM_AWS_DEV_DESTROY",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation and successor confirmations must be unset")
    request = context["request"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    kubeconfig = output / "aws-dev-post-create-qualification.kubeconfig"
    environment = safe_environment(kubeconfig)

    identity = parse_json_bytes(run_logged(output, "aws-identity-post-create", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    cluster = require_cluster(parse_json_bytes(run_logged(output, "eks-cluster-post-create", ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"], environment, repository_root, runner).stdout, "EKS cluster"))

    nodegroups = parse_json_bytes(run_logged(output, "eks-nodegroups-post-create", ["aws", "eks", "list-nodegroups", "--region", AWS_REGION, "--cluster-name", CLUSTER_NAME, "--output", "json"], environment, repository_root, runner).stdout, "EKS nodegroups")
    require(nodegroups.get("nodegroups") == [NODEGROUP_NAME], "EKS nodegroup inventory changed")
    nodegroup = require_nodegroup(parse_json_bytes(run_logged(output, "eks-nodegroup-post-create", ["aws", "eks", "describe-nodegroup", "--region", AWS_REGION, "--cluster-name", CLUSTER_NAME, "--nodegroup-name", NODEGROUP_NAME, "--output", "json"], environment, repository_root, runner).stdout, "EKS nodegroup"))

    addons = parse_json_bytes(run_logged(output, "eks-addons-post-create", ["aws", "eks", "list-addons", "--region", AWS_REGION, "--cluster-name", CLUSTER_NAME, "--output", "json"], environment, repository_root, runner).stdout, "EKS addons")
    require(set(addons.get("addons", [])) == EXPECTED_ADDONS, "EKS managed-addon inventory changed")
    for addon in sorted(EXPECTED_ADDONS):
        value = parse_json_bytes(run_logged(output, f"eks-addon-{addon}-post-create", ["aws", "eks", "describe-addon", "--region", AWS_REGION, "--cluster-name", CLUSTER_NAME, "--addon-name", addon, "--output", "json"], environment, repository_root, runner).stdout, f"EKS addon {addon}")
        observed = value.get("addon", {})
        require(observed.get("addonName") == addon and observed.get("status") == "ACTIVE", f"EKS addon {addon} is not ACTIVE")
        require(observed.get("health", {}).get("issues") == [], f"EKS addon {addon} reports health issues")

    run_logged(output, "kubeconfig-post-create", ["aws", "eks", "update-kubeconfig", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--kubeconfig", str(kubeconfig)], environment, repository_root, runner)
    require(kubeconfig.is_file() and not kubeconfig.is_symlink(), "Private kubeconfig was not created")
    kubeconfig.chmod(0o600)
    kube = ["kubectl", "--kubeconfig", str(kubeconfig), "--request-timeout=30s"]
    current_context = run_logged(output, "kubernetes-current-context-post-create", kube + ["config", "current-context"], environment, repository_root, runner).stdout.decode().strip()
    require(current_context == cluster["arn"], "Private kubeconfig context does not match EKS ARN")
    config = parse_json_bytes(run_logged(output, "kubernetes-config-post-create", kube + ["config", "view", "--minify", "-o", "json"], environment, repository_root, runner).stdout, "Kubernetes config")
    clusters = config.get("clusters")
    require(isinstance(clusters, list) and len(clusters) == 1 and clusters[0].get("cluster", {}).get("server") == cluster["endpoint"], "Private kubeconfig endpoint changed")
    readyz = run_logged(output, "kubernetes-readyz-post-create", kube + ["get", "--raw=/readyz"], environment, repository_root, runner).stdout.decode().strip()
    require(readyz == "ok", "Kubernetes /readyz is not ok")
    require_nodes(parse_json_bytes(run_logged(output, "kubernetes-nodes-post-create", kube + ["get", "nodes", "-o", "json"], environment, repository_root, runner).stdout, "Kubernetes nodes"))
    argocd = run_logged(output, "kubernetes-argocd-namespace-post-create", kube + ["get", "namespace", "argocd", "--ignore-not-found", "-o", "name"], environment, repository_root, runner).stdout.decode().strip()
    require(argocd == "", "Argo CD namespace already exists; use a separate recovery review")

    evidence = {
        "schemaVersion": "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "recoveryControlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current),
        "privateQualificationRequestSha256": file_sha256(context["request_path"]),
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE_SHA256,
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "eksClusterActive": True,
        "kubernetesMinor": KUBERNETES_MINOR,
        "endpointPublicAccess": True,
        "endpointPrivateAccess": True,
        "controlPlaneLoggingEnabled": False,
        "nodegroupActive": True,
        "nodeCount": EXPECTED_NODE_COUNT,
        "readyNodeCount": EXPECTED_NODE_COUNT,
        "managedAddonCount": len(EXPECTED_ADDONS),
        "managedAddonsActive": True,
        "kubernetesReadyz": "ok",
        "privateKubeconfigSha256": file_sha256(kubeconfig),
        "argocdNamespaceAbsent": True,
        "terraformCommandExecuted": False,
        "awsMutationExecuted": False,
        "kubernetesPersistentMutationExecuted": False,
        "gitopsBootstrapExecuted": False,
        "externalSecretsPreflightExecuted": False,
        "automaticRetryPerformed": False,
        "automaticRollbackPerformed": False,
        "automaticTeardownPerformed": False,
    }
    evidence_path = output / "aws-dev-post-create-qualification-evidence.json"
    write_private_json(evidence_path, evidence)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-result-v1",
        "status": "aws-dev-post-create-qualified-for-gitops-bootstrap",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "recovery_control_plane_commit": RECOVERY_CONTROL_PLANE_COMMIT,
        "private_qualification_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_evidence_sha256": RECOVERY_EVIDENCE_SHA256,
        "private_recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "qualification_evidence_sha256": file_sha256(evidence_path),
        "semantic_state_equal": True,
        "environment_created": True,
        "eks_cluster_active": True,
        "kubernetes_minor": KUBERNETES_MINOR,
        "nodegroup_active": True,
        "node_count": EXPECTED_NODE_COUNT,
        "ready_node_count": EXPECTED_NODE_COUNT,
        "managed_addon_count": len(EXPECTED_ADDONS),
        "managed_addons_active": True,
        "kubernetes_readyz": "ok",
        "private_kubeconfig_sha256": file_sha256(kubeconfig),
        "argocd_namespace_absent": True,
        "terraform_command_executed": False,
        "aws_mutation_executed": False,
        "kubernetes_persistent_mutation_executed": False,
        "gitops_bootstrap_executed": False,
        "external_secrets_preflight_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "automatic_teardown_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-gitops-bootstrap-approval-before-external-secrets-preflight-resume",
    }
    result_path = output / "aws-dev-post-create-qualification-result.json"
    write_private_json(result_path, result)
    result["qualification_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-qualification-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(args.private_qualification_request)
        result = redacted_verification(context) if args.phase == "verify" else execute(args.private_qualification_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, QualificationError) as error:
        parser.exit(1, f"AWS-dev post-create qualification stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
