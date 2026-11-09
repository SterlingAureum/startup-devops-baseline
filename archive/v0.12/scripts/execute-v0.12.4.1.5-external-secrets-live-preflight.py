#!/usr/bin/env python3
"""Verify or execute the guarded External Secrets 2.9.0 aws-dev live preflight."""

from __future__ import annotations

import argparse
from collections import Counter
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
CONFIRMATION = "run-reviewed-external-secrets-2.9.0-live-preflight"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
KUBERNETES_MINOR = "1.36"
CURRENT_CHART_VERSION = "2.8.0"
CANDIDATE_CHART_VERSION = "2.9.0"
CANDIDATE_CHART_SHA256 = "da2d5c126a103b4c1b16a9dc1c168c4332a3687144e88ac070e594f81a0b6578"
CANDIDATE_RENDER_SHA256 = "880e6805213cf77cd89cf0e60e03624bc01c74d23a2c61693a1be2a5ce2ca8bb"
EXPECTED_RENDER_OBJECT_COUNT = 37
EXPECTED_IMAGE = "ghcr.io/external-secrets/external-secrets:v2.8.0"
EXPECTED_DEPLOYMENTS = {
    "external-secrets",
    "external-secrets-cert-controller",
    "external-secrets-webhook",
}
EXPECTED_RBAC_COUNTS = {
    "Role": 4,
    "RoleBinding": 2,
    "ClusterRole": 1,
    "ClusterRoleBinding": 1,
}
# Keep high-entropy values physically separate from reviewed path names.  This
# preserves exact immutable bindings without adding a scanner allowlist.
EXPECTED_SOURCE_SHA256S = (
    "fc1f8923376e1bc6f3bd20b6f5e9ee33f3b221ad601888b4c231c5951939dd84",
    "b955c94eff8e3ac8541263f4c2f5da51ee9404ce862c7aef7ed59afc38ef2ff5",
    "da0c2a1f598ecd8a144a66272474634aedcdd46639b77a44170166c539d5779e",
    "7cced6cf1225bf56df253863e304ee601fee8b83f7222357786df6a2e0abee41",
    "40790daf99de314df0d1495f5f8d7520d30a2ae31c42dfabce8351d84264ceb2",
    "b10aa34f356b0ef1e4cd2da26dd90e01b5108aec8e3e64d334ef18395c09a1a0",
)
EXPECTED_SOURCE_PATHS = (
    "delivery/contracts/v0.12.4.1.3-external-secrets-artifact-render-proof.json",
    "delivery/contracts/v0.12.4.1.4-external-secrets-2.9.0-hop-plan.json",
    "clusters/aws/base/platform/external-secrets.yaml",
    "clusters/aws/base/platform/external-secrets-startup-apps.yaml",
    "clusters/aws/base/security/external-secrets/startup-apps/secret-store.yaml",
    "clusters/aws/base/security/external-secrets/startup-apps/demo-api-postgresql.yaml",
)
EXPECTED_SOURCE_DIGESTS = tuple(zip(EXPECTED_SOURCE_PATHS, EXPECTED_SOURCE_SHA256S, strict=True))
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 120
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DRY_RUN_IDENTITY_RE = re.compile(r"^[a-z0-9.-]+/[A-Za-z0-9_.:-]+$")


class PreflightError(ValueError):
    """Raised when a reviewed preflight invariant changes."""


class CommandFailure(RuntimeError):
    """Raised when an approved command fails without exposing its output."""


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_private(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise PreflightError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise PreflightError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise PreflightError(f"{label} must be a valid UTC timestamp") from error
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
        "expectedKubernetesMinor", "privateChartPath", "privateChartSha256",
        "privateRenderPath", "privateRenderSha256", "privateOutputDirectory",
        "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Preflight request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5-external-secrets-live-preflight-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]) is not None, "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION, "AWS region changed")
    require(value["expectedClusterName"] == CLUSTER_NAME, "Cluster name changed")
    require(value["expectedKubernetesMinor"] == KUBERNETES_MINOR, "Kubernetes minor changed")
    require(isinstance(value["privateChartPath"], str), "Private chart path is invalid")
    require(value["privateChartSha256"] == CANDIDATE_CHART_SHA256, "Candidate chart digest changed")
    require(isinstance(value["privateRenderPath"], str), "Private render path is invalid")
    require(value["privateRenderSha256"] == CANDIDATE_RENDER_SHA256, "Candidate render digest changed")
    require(isinstance(value["privateOutputDirectory"], str), "Private output path is invalid")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsReadOnly": True,
        "kubernetesReadOnly": True,
        "kubernetesServerSideDryRun": True,
        "kubernetesPersistentMutation": False,
        "gitMutation": False,
        "argocdOperation": False,
        "helmOperation": False,
        "secretValueRead": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise PreflightError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def validate_repository_sources(repository_root: Path) -> None:
    for relative, expected in EXPECTED_SOURCE_DIGESTS:
        path = repository_root / relative
        require(path.is_file() and file_sha256(path) == expected, f"Reviewed source changed: {relative}")
    application = (repository_root / "clusters/aws/base/platform/external-secrets.yaml").read_text()
    require("targetRevision: 2.8.0" in application, "External Secrets chart pin changed before preflight")
    require("targetRevision: 2.9.0" not in application, "Candidate chart pin was applied before preflight")


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private preflight request")
    require(not is_within(private_request, repository_root), "Private preflight request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private preflight request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Preflight approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Preflight approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Preflight must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Preflight requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main, "HEAD does not equal reviewed main")
    require(git_runner(["rev-parse", "origin/main"]) == expected_main, "origin/main does not equal reviewed main")
    validate_repository_sources(repository_root)

    chart = require_private_file(Path(request["privateChartPath"]), "Private candidate chart")
    render = require_private_file(Path(request["privateRenderPath"]), "Private candidate render")
    for path, expected, label in (
        (chart, request["privateChartSha256"], "Candidate chart"),
        (render, request["privateRenderSha256"], "Candidate render"),
    ):
        require(not is_within(path, repository_root), f"{label} must remain outside the repository")
        require(file_sha256(path) == expected, f"{label} digest changed")
    require(chart != render, "Candidate chart and render paths must differ")
    output = require_new_private_directory(Path(request["privateOutputDirectory"]), "Private preflight output")
    require(not is_within(output, repository_root), "Private preflight output must remain outside the repository")
    return {
        "request": request,
        "request_path": private_request,
        "chart": chart,
        "render": render,
        "output": output,
        "remaining": remaining,
    }


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "external-secrets-2.9.0-live-preflight-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "candidate_chart_sha256": request["privateChartSha256"],
        "candidate_render_sha256": request["privateRenderSha256"],
        "candidate_render_object_count": EXPECTED_RENDER_OBJECT_COUNT,
        "remaining_preflight_approval_seconds": context["remaining"],
        "preflight_execution_authorized": False,
        "git_pin_mutation_authorized": False,
        "argocd_operation_authorized": False,
        "secret_value_read_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-external-secrets-live-preflight-approval",
    }


def safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("CONFIRM_"):
            del environment[key]
    environment.pop("KUBECTL_EXTERNAL_DIFF", None)
    environment["AWS_REGION"] = AWS_REGION
    environment["AWS_DEFAULT_REGION"] = AWS_REGION
    return environment


def run_logged(
    output: Path,
    label: str,
    arguments: list[str],
    environment: dict[str, str],
    runner: CommandRunner,
    repository_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, repository_root)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out; preserve private evidence and do not retry") from error
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)
    if result.returncode:
        raise CommandFailure(f"{label} failed; preserve private evidence and do not retry")
    return result


def ready_condition(resource: dict[str, Any]) -> bool:
    return any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in resource.get("status", {}).get("conditions", [])
    )


def validate_application(application: dict[str, Any], name: str, expected_main: str) -> dict[str, Any]:
    metadata = application.get("metadata", {})
    spec = application.get("spec", {})
    source = spec.get("source", {})
    status = application.get("status", {})
    require(metadata.get("name") == name and metadata.get("namespace") == "argocd", f"{name} identity changed")
    require(status.get("sync", {}).get("status") == "Synced", f"{name} is not Synced")
    require(status.get("health", {}).get("status") == "Healthy", f"{name} is not Healthy")
    require(not application.get("operation"), f"{name} has an active operation")
    automated = spec.get("syncPolicy", {}).get("automated", {})
    require(automated.get("prune") is True and automated.get("selfHeal") is True, f"{name} automated sync changed")
    if name == "external-secrets":
        require(source.get("repoURL") == "https://charts.external-secrets.io", "External Secrets chart repository changed")
        require(source.get("chart") == "external-secrets", "External Secrets chart identity changed")
        require(source.get("targetRevision") == CURRENT_CHART_VERSION, "External Secrets live chart version changed")
    else:
        require(source.get("repoURL") == "https://github.com/SterlingAureum/startup-devops-baseline.git", "Resource Application repository changed")
        require(source.get("targetRevision") == "main", "Resource Application target revision changed")
        require(source.get("path") == "clusters/aws/overlays/dev/security/external-secrets/startup-apps", "Resource Application path changed")
        require(status.get("sync", {}).get("revision") == expected_main, "Resource Application did not resolve reviewed main")
    return {
        "metadata": {"name": metadata.get("name"), "namespace": metadata.get("namespace")},
        "spec": spec,
        "syncStatus": status.get("sync", {}).get("status"),
        "healthStatus": status.get("health", {}).get("status"),
        "syncRevision": status.get("sync", {}).get("revision"),
        "operationPresent": bool(application.get("operation")),
    }


def deployment_ready(deployment: dict[str, Any]) -> bool:
    replicas = deployment.get("spec", {}).get("replicas")
    status = deployment.get("status", {})
    return (
        isinstance(replicas, int)
        and replicas > 0
        and status.get("observedGeneration") == deployment.get("metadata", {}).get("generation")
        and status.get("readyReplicas") == replicas
        and status.get("updatedReplicas") == replicas
        and status.get("availableReplicas") == replicas
    )


def validate_deployments(value: dict[str, Any]) -> list[dict[str, Any]]:
    items = value.get("items")
    require(isinstance(items, list) and len(items) == 3, "External Secrets Deployment count changed")
    require({item.get("metadata", {}).get("name") for item in items} == EXPECTED_DEPLOYMENTS, "External Secrets Deployment inventory changed")
    projections = []
    for item in sorted(items, key=lambda candidate: candidate.get("metadata", {}).get("name", "")):
        name = item.get("metadata", {}).get("name")
        require(item.get("metadata", {}).get("namespace") == "external-secrets", f"Deployment namespace changed: {name}")
        require(deployment_ready(item), f"Deployment is not fully available: {name}")
        pod_spec = item.get("spec", {}).get("template", {}).get("spec", {})
        containers = pod_spec.get("containers", [])
        require(isinstance(containers, list) and containers, f"Deployment containers missing: {name}")
        require({container.get("image") for container in containers} == {EXPECTED_IMAGE}, f"Deployment image changed: {name}")
        if name == "external-secrets":
            require(pod_spec.get("serviceAccountName") == "external-secrets", "Main controller ServiceAccount changed")
        projections.append({
            "metadata": {"name": name, "namespace": "external-secrets"},
            "spec": item.get("spec"),
            "available": True,
        })
    return projections


def validate_service_account(value: dict[str, Any], account: str) -> dict[str, Any]:
    metadata = value.get("metadata", {})
    require(metadata.get("name") == "external-secrets" and metadata.get("namespace") == "external-secrets", "Controller ServiceAccount identity changed")
    role_arn = (metadata.get("annotations") or {}).get("eks.amazonaws.com/role-arn")
    expected = f"arn:aws:iam::{account}:role/startup-devops-baseline-dev-external-secrets-role"
    require(role_arn == expected, "Controller ServiceAccount IRSA role changed")
    return {
        "metadata": {"name": metadata.get("name"), "namespace": metadata.get("namespace")},
        "irsaRoleSha256": sha256_bytes(role_arn.encode()),
        "automountServiceAccountToken": value.get("automountServiceAccountToken"),
    }


def validate_rbac(value: dict[str, Any]) -> list[dict[str, Any]]:
    items = value.get("items")
    require(isinstance(items, list), "RBAC inventory is invalid")
    counts = Counter(item.get("kind") for item in items)
    require(dict(counts) == EXPECTED_RBAC_COUNTS, "External Secrets RBAC inventory changed")
    projections = []
    for item in sorted(items, key=lambda candidate: (candidate.get("kind", ""), candidate.get("metadata", {}).get("namespace", ""), candidate.get("metadata", {}).get("name", ""))):
        metadata = item.get("metadata", {})
        projections.append({
            "kind": item.get("kind"),
            "metadata": {"name": metadata.get("name"), "namespace": metadata.get("namespace")},
            "rules": item.get("rules"),
            "roleRef": item.get("roleRef"),
            "subjects": item.get("subjects"),
        })
    return projections


def validate_crds(value: dict[str, Any]) -> list[dict[str, Any]]:
    items = value.get("items")
    require(isinstance(items, list) and len(items) == 2, "Repository-used CRD inventory changed")
    expected = {"externalsecrets.external-secrets.io", "secretstores.external-secrets.io"}
    require({item.get("metadata", {}).get("name") for item in items} == expected, "Repository-used CRD names changed")
    projections = []
    for item in sorted(items, key=lambda candidate: candidate.get("metadata", {}).get("name", "")):
        versions = item.get("spec", {}).get("versions", [])
        v1 = [version for version in versions if version.get("name") == "v1"]
        require(len(v1) == 1 and v1[0].get("served") is True and v1[0].get("storage") is True, "Repository-used CRD does not serve and store v1")
        projections.append({"name": item.get("metadata", {}).get("name"), "spec": item.get("spec")})
    return projections


def validate_secret_store(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata", {})
    require(metadata.get("name") == "aws-secrets-manager" and metadata.get("namespace") == "startup-apps", "SecretStore identity changed")
    aws = value.get("spec", {}).get("provider", {}).get("aws", {})
    require(aws.get("service") == "SecretsManager" and aws.get("region") == AWS_REGION, "SecretStore AWS provider changed")
    require(ready_condition(value), "SecretStore is not Ready")
    return {"metadata": {"name": metadata.get("name"), "namespace": metadata.get("namespace")}, "spec": value.get("spec"), "ready": True}


def validate_external_secret(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata", {})
    require(metadata.get("name") == "demo-api-postgresql" and metadata.get("namespace") == "startup-apps", "ExternalSecret identity changed")
    require("force-sync" not in (metadata.get("annotations") or {}), "ExternalSecret force-sync annotation is present")
    spec = value.get("spec", {})
    require(spec.get("secretStoreRef") == {"name": "aws-secrets-manager", "kind": "SecretStore"}, "ExternalSecret store reference changed")
    data = spec.get("data")
    require(isinstance(data, list) and len(data) == 1, "ExternalSecret data mapping changed")
    remote = data[0].get("remoteRef", {})
    require(data[0].get("secretKey") == "DATABASE_URL", "ExternalSecret target key changed")
    require(remote.get("key") == "startup-devops-baseline-dev/demo-api/postgresql", "ExternalSecret remote identity changed")
    require(remote.get("property") == "DATABASE_URL" and remote.get("version") == "AWSCURRENT", "ExternalSecret AWSCURRENT reference changed")
    require(remote.get("conversionStrategy") == "Default" and remote.get("decodingStrategy") == "None" and remote.get("metadataPolicy") == "None", "ExternalSecret explicit strategy changed")
    require(ready_condition(value), "ExternalSecret is not Ready")
    return {
        "metadata": {"name": metadata.get("name"), "namespace": metadata.get("namespace")},
        "spec": spec,
        "ready": True,
        "forceSyncPresent": False,
    }


def snapshot_commands() -> list[tuple[str, list[str]]]:
    return [
        ("operator-application", ["kubectl", "-n", "argocd", "get", "application", "external-secrets", "-o", "json"]),
        ("resource-application", ["kubectl", "-n", "argocd", "get", "application", "external-secrets-startup-apps", "-o", "json"]),
        ("deployments", ["kubectl", "-n", "external-secrets", "get", "deployment", "external-secrets", "external-secrets-cert-controller", "external-secrets-webhook", "-o", "json"]),
        ("serviceaccount", ["kubectl", "-n", "external-secrets", "get", "serviceaccount", "external-secrets", "-o", "json"]),
        ("rbac", ["kubectl", "get", "roles,rolebindings,clusterroles,clusterrolebindings", "--all-namespaces", "-l", "app.kubernetes.io/instance=external-secrets", "-o", "json"]),
        ("crds", ["kubectl", "get", "customresourcedefinition", "externalsecrets.external-secrets.io", "secretstores.external-secrets.io", "-o", "json"]),
        ("secretstore", ["kubectl", "-n", "startup-apps", "get", "secretstore", "aws-secrets-manager", "-o", "json"]),
        ("externalsecret", ["kubectl", "-n", "startup-apps", "get", "externalsecret", "demo-api-postgresql", "-o", "json"]),
    ]


def collect_snapshot(
    output: Path,
    prefix: str,
    expected_main: str,
    account: str,
    environment: dict[str, str],
    runner: CommandRunner,
    repository_root: Path,
) -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {}
    for label, command in snapshot_commands():
        result = run_logged(output, f"{prefix}-{label}", command, environment, runner, repository_root)
        require(result.stderr == b"", f"{prefix}-{label} produced stderr")
        values[label] = parse_json_bytes(result.stdout, f"{prefix}-{label}")
    projection = {
        "operatorApplication": validate_application(values["operator-application"], "external-secrets", expected_main),
        "resourceApplication": validate_application(values["resource-application"], "external-secrets-startup-apps", expected_main),
        "deployments": validate_deployments(values["deployments"]),
        "serviceAccount": validate_service_account(values["serviceaccount"], account),
        "rbac": validate_rbac(values["rbac"]),
        "crds": validate_crds(values["crds"]),
        "secretStore": validate_secret_store(values["secretstore"]),
        "externalSecret": validate_external_secret(values["externalsecret"]),
    }
    return projection


def validate_dry_run_stdout(value: bytes) -> list[str]:
    try:
        text = value.decode()
    except UnicodeDecodeError as error:
        raise PreflightError("Server-side dry-run stdout is not UTF-8") from error
    identities = [line.strip() for line in text.splitlines() if line.strip()]
    require(len(identities) == EXPECTED_RENDER_OBJECT_COUNT, "Server-side dry-run object count changed")
    require(len(set(identities)) == len(identities), "Server-side dry-run emitted duplicate identities")
    require(all(DRY_RUN_IDENTITY_RE.fullmatch(item) is not None for item in identities), "Server-side dry-run emitted non-identity output")
    return identities


def command_artifact_hashes(output: Path) -> dict[str, str]:
    paths = sorted(path for path in output.iterdir() if path.suffix in {".stdout", ".stderr"})
    require(paths, "No private command evidence was recorded")
    require(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths), "Private command evidence mode changed")
    return {path.name: file_sha256(path) for path in paths}


def execute(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT") == CONFIRMATION, f"Set CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT={CONFIRMATION}")
    forbidden_confirmations = (
        "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN",
        "CONFIRM_EXTERNAL_SECRETS_ROLLBACK",
        "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden_confirmations), "Mutation confirmations must be unset")
    output = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment()
    request = context["request"]

    identity_result = run_logged(output, "aws-identity", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, runner, repository_root)
    require(identity_result.stderr == b"", "AWS identity produced stderr")
    identity = parse_json_bytes(identity_result.stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")

    cluster_result = run_logged(output, "eks-cluster", ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"], environment, runner, repository_root)
    require(cluster_result.stderr == b"", "EKS cluster read produced stderr")
    cluster = parse_json_bytes(cluster_result.stdout, "EKS cluster").get("cluster", {})
    require(cluster.get("name") == CLUSTER_NAME and cluster.get("status") == "ACTIVE", "aws-dev EKS identity or status changed")
    require(cluster.get("version") == KUBERNETES_MINOR, "aws-dev Kubernetes minor changed")
    cluster_arn = cluster.get("arn")
    require(isinstance(cluster_arn, str) and cluster_arn == f"arn:aws:eks:{AWS_REGION}:{request['expectedAwsAccountId']}:cluster/{CLUSTER_NAME}", "aws-dev EKS ARN changed")

    context_result = run_logged(output, "kubectl-context", ["kubectl", "config", "current-context"], environment, runner, repository_root)
    require(context_result.stderr == b"" and context_result.stdout.decode().strip() == cluster_arn, "kubectl context is not the exact aws-dev EKS ARN")
    readyz_result = run_logged(output, "kubernetes-readyz", ["kubectl", "get", "--raw=/readyz"], environment, runner, repository_root)
    require(readyz_result.stderr == b"" and readyz_result.stdout.decode().strip() == "ok", "Kubernetes readyz changed")

    before = collect_snapshot(output, "before", request["expectedMainCommit"], request["expectedAwsAccountId"], environment, runner, repository_root)
    before_digest = sha256_bytes(canonical_json(before))
    dry_run = run_logged(
        output,
        "server-side-dry-run",
        [
            "kubectl", "apply", "--server-side", "--dry-run=server",
            "--field-manager=v0.12.4.1.5-external-secrets-preflight",
            "-o", "name", "-f", str(context["render"]),
        ],
        environment,
        runner,
        repository_root,
    )
    require(dry_run.stderr == b"", "Server-side dry-run produced stderr")
    dry_run_identities = validate_dry_run_stdout(dry_run.stdout)
    after = collect_snapshot(output, "after", request["expectedMainCommit"], request["expectedAwsAccountId"], environment, runner, repository_root)
    after_digest = sha256_bytes(canonical_json(after))
    require(after_digest == before_digest, "Protected live projection changed during server-side dry-run")

    evidence = {
        "schemaVersion": "v0.12.4.1.5-external-secrets-live-preflight-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "privateRequestSha256": file_sha256(context["request_path"]),
        "candidateChartSha256": request["privateChartSha256"],
        "candidateRenderSha256": request["privateRenderSha256"],
        "clusterVersion": cluster.get("version"),
        "protectedProjectionBeforeSha256": before_digest,
        "protectedProjectionAfterSha256": after_digest,
        "serverSideDryRunIdentityInventorySha256": sha256_bytes(canonical_json(sorted(dry_run_identities))),
        "serverSideDryRunObjectCount": len(dry_run_identities),
        "deploymentCount": len(before["deployments"]),
        "rbacKindCounts": EXPECTED_RBAC_COUNTS,
        "repositoryUsedCrdCount": len(before["crds"]),
        "commandArtifactSha256s": command_artifact_hashes(output),
        "secretValuesRead": False,
        "persistentMutationExecuted": False,
    }
    evidence_path = output / "preflight-evidence.json"
    write_private(evidence_path, canonical_json(evidence))
    result = {
        "schemaVersion": "v0.12.4.1.5-external-secrets-live-preflight-result-v1",
        "status": "external-secrets-2.9.0-live-preflight-complete-awaiting-human-review",
        "completed_at_utc": utc_text(datetime.now(timezone.utc)),
        "control_plane_commit": request["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "candidate_chart_sha256": request["privateChartSha256"],
        "candidate_render_sha256": request["privateRenderSha256"],
        "preflight_evidence_sha256": file_sha256(evidence_path),
        "protected_projection_sha256": before_digest,
        "server_side_dry_run_identity_inventory_sha256": evidence["serverSideDryRunIdentityInventorySha256"],
        "server_side_dry_run_object_count": len(dry_run_identities),
        "cluster_version": cluster.get("version"),
        "current_chart_version": CURRENT_CHART_VERSION,
        "candidate_chart_version": CANDIDATE_CHART_VERSION,
        "deployment_count": len(before["deployments"]),
        "rbac_object_count": len(before["rbac"]),
        "repository_used_crd_count": len(before["crds"]),
        "operator_application_synced_healthy_idle": True,
        "resource_application_synced_healthy_idle": True,
        "secret_store_ready": True,
        "external_secret_ready_and_awscurrent": True,
        "server_side_dry_run_executed": True,
        "protected_projection_unchanged": True,
        "persistent_kubernetes_mutation_executed": False,
        "git_pin_mutation_executed": False,
        "argocd_operation_executed": False,
        "helm_operation_executed": False,
        "aws_mutation_executed": False,
        "secret_value_read_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "human-review-private-preflight-before-v0.12.4.1.5.1-evidence-record",
    }
    result_path = output / "preflight-result.json"
    write_private(result_path, canonical_json(result))
    result["preflight_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-preflight-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = redacted_verification(verify_inputs(args.private_preflight_request))
        else:
            result = execute(args.private_preflight_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, PreflightError) as error:
        parser.exit(1, f"External Secrets live preflight stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
