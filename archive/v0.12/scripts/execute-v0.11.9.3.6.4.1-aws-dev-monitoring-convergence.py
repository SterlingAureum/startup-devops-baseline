#!/usr/bin/env python3
"""Verify or execute the reviewed aws-dev monitoring convergence repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PREPARE_GRAFANA_SECRET = ROOT / "scripts/prepare-aws-dev-grafana-secret.py"
AWS_DEV_RELEASE = ROOT / "apps/demo-api/helm/values/releases/aws-dev.yaml"
AWS_DEV_RELEASE_SHA256 = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
ROOT_APPLICATION = "startup-devops-aws-dev-root"
DEMO_APPLICATION = "demo-api-aws-dev"
MONITORING_APPLICATION = "monitoring-aws-dev"
MONITORING_CHART_VERSION = "88.5.0"
GRAFANA_SECRET = "observability-grafana-admin"
GRAFANA_DEPLOYMENT = "observability-metrics-grafana"
EXPECTED_RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"
EXPECTED_APPLICATION_VERSION = "sha-cf0a6bc"
EXPECTED_IMAGE_DIGEST = "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623"
EXPECTED_SOURCE_COMMIT = "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-monitoring-convergence"
EXECUTION_CONFIRMATION = "converge-reviewed-aws-dev-monitoring"
INTERNAL_SECRET_CONFIRMATION = "prepare-aws-dev"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
ReadRunner = Callable[[list[str]], str]
ConvergeRunner = Callable[[str], int]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise CommandFailure(detail)
    return result.stdout.strip()


def run_read_command(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"{arguments[0]} command failed"
        raise CommandFailure(detail)
    return result.stdout.strip()


def parse_json(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} returned malformed JSON") from error
    require(isinstance(value, dict), f"{label} must return a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_expected_account() -> str:
    account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    require(bool(ACCOUNT_RE.fullmatch(account)), "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    return account


def validate_exact_main(expected_commit: str, git_runner: GitRunner) -> None:
    require(bool(COMMIT_RE.fullmatch(expected_commit)), "Expected control-plane commit must be 40 lowercase hex characters")
    require(git_runner(["branch", "--show-current"]) == "main", "Monitoring convergence must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Monitoring convergence requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_commit, "HEAD does not equal the reviewed commit")
    require(git_runner(["rev-parse", "origin/main"]) == expected_commit, "origin/main does not equal the reviewed commit")
    remote = git_runner(["ls-remote", "origin", "refs/heads/main"]).splitlines()
    require(remote == [f"{expected_commit}\trefs/heads/main"], "Remote main does not equal the reviewed commit")


def require_application(
    application: dict[str, Any],
    name: str,
    expected_commit: str,
    *,
    path: str,
) -> None:
    source = application.get("spec", {}).get("source", {})
    require(application.get("metadata", {}).get("name") == name, f"{name} identity changed")
    require(source.get("repoURL") == "https://github.com/SterlingAureum/startup-devops-baseline.git", f"{name} repository changed")
    require(source.get("targetRevision") == "main", f"{name} targetRevision must remain main")
    require(source.get("path") == path, f"{name} source path changed")
    require(application.get("status", {}).get("sync", {}).get("status") == "Synced", f"{name} is not Synced")
    require(application.get("status", {}).get("health", {}).get("status") == "Healthy", f"{name} is not Healthy")
    require(application.get("status", {}).get("sync", {}).get("revision") == expected_commit, f"{name} did not resolve reviewed main")


def workload_is_ready(workload: dict[str, Any]) -> bool:
    spec_replicas = workload.get("spec", {}).get("replicas")
    status = workload.get("status", {})
    return (
        isinstance(spec_replicas, int)
        and spec_replicas > 0
        and status.get("observedGeneration") == workload.get("metadata", {}).get("generation")
        and status.get("readyReplicas") == spec_replicas
        and status.get("updatedReplicas") == spec_replicas
        and status.get("availableReplicas") == spec_replicas
    )


def read_live_state(expected_commit: str, read_runner: ReadRunner) -> dict[str, Any]:
    expected_account = read_expected_account()
    actual_account = read_runner(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    require(actual_account == expected_account, "AWS caller account does not match EXPECTED_AWS_ACCOUNT_ID")

    cluster = read_runner([
        "aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME,
        "--query", "cluster.[status,version,arn]", "--output", "text",
    ]).split()
    require(len(cluster) == 3, "EKS status/version/ARN response is incomplete")
    require(cluster[0] == "ACTIVE", "aws-dev EKS cluster must be ACTIVE")
    require(read_runner(["kubectl", "config", "current-context"]) == cluster[2], "kubectl context is not the exact aws-dev EKS ARN")
    require(read_runner(["kubectl", "get", "--raw=/readyz"]) == "ok", "Kubernetes /readyz is not ok")

    root = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "application", ROOT_APPLICATION, "-o", "json"]),
        "aws-dev Root Application",
    )
    require_application(root, ROOT_APPLICATION, expected_commit, path="clusters/aws/overlays/dev")

    demo_application = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "application", DEMO_APPLICATION, "-o", "json"]),
        "demo-api Application",
    )
    require_application(demo_application, DEMO_APPLICATION, expected_commit, path="apps/demo-api/helm")

    demo = parse_json(
        read_runner(["kubectl", "-n", "startup-apps", "get", "deployment", "demo-api", "-o", "json"]),
        "demo-api Deployment",
    )
    require(workload_is_ready(demo), "demo-api Deployment is not fully Ready")
    annotations = demo.get("metadata", {}).get("annotations", {})
    require(annotations.get("platform.startup.dev/release-id") == EXPECTED_RELEASE_ID, "demo-api release ID changed")
    require(annotations.get("platform.startup.dev/application-version") == EXPECTED_APPLICATION_VERSION, "demo-api application version changed")
    require(annotations.get("platform.startup.dev/image-digest") == EXPECTED_IMAGE_DIGEST, "demo-api image digest changed")
    require(annotations.get("platform.startup.dev/source-commit") == EXPECTED_SOURCE_COMMIT, "demo-api source commit changed")

    postgres = parse_json(
        read_runner(["kubectl", "-n", "data-platform", "get", "cluster", "postgresql-baseline", "-o", "json"]),
        "CloudNativePG Cluster",
    )
    conditions = postgres.get("status", {}).get("conditions", [])
    require(
        postgres.get("status", {}).get("instances", 0) > 0
        and postgres.get("status", {}).get("readyInstances") == postgres.get("status", {}).get("instances")
        and any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions),
        "CloudNativePG Cluster is not fully Ready",
    )

    monitoring = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "application", MONITORING_APPLICATION, "-o", "json"]),
        "monitoring Application",
    )
    source = monitoring.get("spec", {}).get("source", {})
    require(source.get("chart") == "kube-prometheus-stack", "monitoring chart changed")
    require(source.get("targetRevision") == MONITORING_CHART_VERSION, "monitoring chart version changed")
    require(monitoring.get("status", {}).get("sync", {}).get("status") == "Synced", "monitoring Application is not Synced")

    secret_name = read_runner([
        "kubectl", "-n", "observability", "get", "secret", GRAFANA_SECRET,
        "--ignore-not-found", "-o", "name",
    ])
    require(secret_name in ("", f"secret/{GRAFANA_SECRET}"), "Grafana Secret identity response changed")

    grafana = parse_json(
        read_runner(["kubectl", "-n", "observability", "get", "deployment", GRAFANA_DEPLOYMENT, "-o", "json"]),
        "Grafana Deployment",
    )
    monitoring_health = monitoring.get("status", {}).get("health", {}).get("status")
    grafana_ready = workload_is_ready(grafana)
    if monitoring_health == "Healthy":
        require(secret_name == f"secret/{GRAFANA_SECRET}", "Healthy monitoring has no independent Grafana Secret")
        require(grafana_ready, "Grafana Deployment is not fully Ready")
        convergence_state = "already-converged"
    else:
        require(monitoring_health == "Degraded", "monitoring health is neither reviewed Degraded nor Healthy")
        require(secret_name == "", "monitoring is Degraded for a reason other than the reviewed missing Secret")
        require(not grafana_ready, "Grafana is Ready despite the missing reviewed Secret")
        convergence_state = "missing-secret-repair-required"

    return {
        "control_plane_commit": expected_commit,
        "cluster_status": cluster[0],
        "cluster_version": cluster[1],
        "kubernetes_readyz": "ok",
        "root_application_status": "Synced/Healthy",
        "demo_application_status": "Synced/Healthy",
        "demo_deployment_ready": True,
        "database_ready": True,
        "monitoring_application_status": f"Synced/{monitoring_health}",
        "grafana_secret_status": "present" if secret_name else "absent",
        "grafana_deployment_ready": grafana_ready,
        "convergence_state": convergence_state,
        "candidate_release_id": EXPECTED_RELEASE_ID,
    }


def verify_live_inputs(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_MONITORING_PREFLIGHT") == OBSERVATION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_MONITORING_PREFLIGHT={OBSERVATION_CONFIRMATION}",
    )
    validate_exact_main(expected_commit, git_runner)
    require(file_sha256(AWS_DEV_RELEASE) == AWS_DEV_RELEASE_SHA256, "aws-dev release identity changed")
    return read_live_state(expected_commit, read_runner)


def run_convergence(expected_account: str) -> int:
    environment = os.environ.copy()
    environment.update(
        EXPECTED_AWS_ACCOUNT_ID=expected_account,
        AWS_REGION=AWS_REGION,
        CONFIRM_GRAFANA_SECRET=INTERNAL_SECRET_CONFIRMATION,
    )
    prepared = subprocess.run([str(PREPARE_GRAFANA_SECRET)], cwd=ROOT, env=environment, check=False)
    if prepared.returncode != 0:
        return prepared.returncode
    commands = (
        [
            "kubectl", "-n", "observability", "wait", "--for=condition=Available",
            f"deployment/{GRAFANA_DEPLOYMENT}", "--timeout=600s",
        ],
        [
            "kubectl", "-n", "argocd", "wait",
            "--for=jsonpath={.status.health.status}=Healthy",
            f"application/{MONITORING_APPLICATION}", "--timeout=600s",
        ],
    )
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def verification_result(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-monitoring-convergence-inputs-verified",
        **inventory,
        "execution_authorized": False,
        "read_only_checks": [
            "clean-exact-remote-main",
            "aws-caller-and-exact-eks-context",
            "root-and-demo-exact-main",
            "demo-immutable-identity-and-readiness",
            "database-readiness",
            "monitoring-chart-and-sync-state",
            "grafana-secret-name-only-discovery",
            "grafana-deployment-readiness",
        ],
        "next_action": "obtain-separate-monitoring-convergence-approval",
    }


def execute(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
    converge_runner: ConvergeRunner = run_convergence,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_MONITORING_CONVERGENCE") == EXECUTION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_MONITORING_CONVERGENCE={EXECUTION_CONFIRMATION}",
    )
    inventory = verify_live_inputs(expected_commit, git_runner, read_runner)
    action = "preserved"
    if inventory["convergence_state"] == "missing-secret-repair-required":
        return_code = converge_runner(read_expected_account())
        if return_code != 0:
            raise CommandFailure(
                f"aws-dev monitoring convergence exited {return_code}; preserve the live state and do not rerun or qualify before review"
            )
        action = "created"
    validate_exact_main(expected_commit, git_runner)
    final_state = read_live_state(expected_commit, read_runner)
    require(final_state["convergence_state"] == "already-converged", "monitoring did not reach the reviewed converged state")
    return {
        "status": "aws-dev-monitoring-convergence-complete",
        "control_plane_commit": expected_commit,
        "candidate_release_id": EXPECTED_RELEASE_ID,
        "grafana_secret_action": action,
        "grafana_secret_values_exposed": False,
        "grafana_deployment_ready": True,
        "monitoring_application_synced": True,
        "monitoring_application_healthy": True,
        "root_application_redeployed": False,
        "runtime_qualified": False,
        "traffic_generated": False,
        "progressive_delivery_promoted": False,
        "automatic_teardown_executed": False,
        "next_action": "review-separate-aws-dev-runtime-qualification",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = verification_result(verify_live_inputs(args.expected_control_plane_commit))
        else:
            result = execute(args.expected_control_plane_commit)
    except (CommandFailure, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"aws-dev monitoring convergence stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
