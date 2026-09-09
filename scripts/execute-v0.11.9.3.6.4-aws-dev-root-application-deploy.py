#!/usr/bin/env python3
"""Verify or execute the separately reviewed aws-dev Root Application deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ROOT = ROOT / "scripts/deploy-aws-dev-root-app.sh"
TF_DIR = ROOT / "infra/terraform/aws/environments/dev"
ROOT_SOURCE = ROOT / "clusters/aws/overlays/dev/root-app.yaml"
AWS_DEV_RELEASE = ROOT / "apps/demo-api/helm/values/releases/aws-dev.yaml"
ROOT_SOURCE_SHA256 = "6f0fc680b04b7df3194549e626764a758856ebfb7cf38e806f573c4b0297e11f"
AWS_DEV_RELEASE_SHA256 = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
ROOT_APPLICATION = "startup-devops-aws-dev-root"
ALB_APPLICATION = "aws-load-balancer-controller"
ARGOCD_VERSION = "v3.5.2"
ALB_CHART_VERSION = "1.14.0"
EXPECTED_STATE_ADDRESS_COUNT = 103
EXPECTED_RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"
OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-root-deploy"
EXECUTION_CONFIRMATION = "deploy-reviewed-aws-dev-root-application"
INTERNAL_ENTRYPOINT_CONFIRMATION = "execute-validated-aws-dev-root-deploy"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VPC_RE = re.compile(r"^vpc-[0-9a-f]+$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
EXPECTED_ARGOCD_IMAGES = {
    "argocd-applicationset-controller": "quay.io/argoproj/argocd:v3.5.2",
    "argocd-dex-server": "ghcr.io/dexidp/dex:v2.45.1",
    "argocd-notifications-controller": "quay.io/argoproj/argocd:v3.5.2",
    "argocd-redis": "public.ecr.aws/docker/library/redis:8.2.3-alpine",
    "argocd-repo-server": "quay.io/argoproj/argocd:v3.5.2",
    "argocd-server": "quay.io/argoproj/argocd:v3.5.2",
    "argocd-application-controller": "quay.io/argoproj/argocd:v3.5.2",
}


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
ReadRunner = Callable[[list[str]], str]
DeployRunner = Callable[[str], int]


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
    require(git_runner(["branch", "--show-current"]) == "main", "Root deployment must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Root deployment requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_commit, "HEAD does not equal the reviewed commit")
    require(git_runner(["rev-parse", "origin/main"]) == expected_commit, "origin/main does not equal the reviewed commit")
    remote = git_runner(["ls-remote", "origin", "refs/heads/main"]).splitlines()
    require(remote == [f"{expected_commit}\trefs/heads/main"], "Remote main does not equal the reviewed commit")


def require_arn_account(value: str, expected_account: str, label: str) -> None:
    match = re.fullmatch(r"arn:[^:]+:[^:]+:[^:]*:([0-9]{12}):.+", value)
    require(match is not None and match.group(1) == expected_account, f"{label} is not in the reviewed AWS account")


def terraform_output(read_runner: ReadRunner, name: str) -> str:
    value = read_runner(["terraform", f"-chdir={TF_DIR}", "output", "-raw", name])
    require(bool(value), f"Terraform output {name} is empty")
    return value


def verify_argocd(read_runner: ReadRunner, vpc_id: str) -> None:
    workloads = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "deployments,statefulsets", "-o", "json"]),
        "Argo CD workload inventory",
    ).get("items")
    require(isinstance(workloads, list), "Argo CD workload inventory has no items")
    observed: dict[str, dict[str, Any]] = {}
    for workload in workloads:
        name = workload.get("metadata", {}).get("name")
        require(isinstance(name, str) and name not in observed, "Argo CD workload name is missing or duplicated")
        observed[name] = workload
    require(set(observed) == set(EXPECTED_ARGOCD_IMAGES), "Argo CD workload inventory changed")
    for name, expected_image in EXPECTED_ARGOCD_IMAGES.items():
        workload = observed[name]
        replicas = workload.get("status", {}).get("replicas", 0)
        ready = workload.get("status", {}).get("readyReplicas", 0)
        images = [item.get("image") for item in workload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])]
        require(isinstance(replicas, int) and replicas > 0 and ready == replicas, f"Argo CD workload {name} is not fully Ready")
        require(expected_image in images, f"Argo CD workload {name} image changed")

    applications = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "applications.argoproj.io", "-o", "json"]),
        "Argo CD Application inventory",
    ).get("items")
    require(isinstance(applications, list), "Argo CD Application inventory has no items")
    names = [item.get("metadata", {}).get("name") for item in applications]
    require(names == [ALB_APPLICATION], "Argo CD Application inventory must contain only the reviewed ALB Application")

    alb = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "application", ALB_APPLICATION, "-o", "json"]),
        "AWS Load Balancer Controller Application",
    )
    source = alb.get("spec", {}).get("source", {})
    values = source.get("helm", {}).get("valuesObject", {})
    require(alb.get("status", {}).get("sync", {}).get("status") == "Synced", "ALB Application is not Synced")
    require(alb.get("status", {}).get("health", {}).get("status") == "Healthy", "ALB Application is not Healthy")
    require(source.get("chart") == ALB_APPLICATION, "ALB Application chart changed")
    require(source.get("targetRevision") == ALB_CHART_VERSION, "ALB Application chart version changed")
    require(alb.get("spec", {}).get("destination", {}).get("namespace") == "kube-system", "ALB destination namespace changed")
    require(values.get("clusterName") == CLUSTER_NAME, "ALB Application cluster name changed")
    require(values.get("region") == AWS_REGION, "ALB Application region changed")
    require(values.get("vpcId") == vpc_id, "ALB Application VPC ID does not match Terraform")

    deployment = parse_json(
        read_runner(["kubectl", "-n", "kube-system", "get", "deployment", ALB_APPLICATION, "-o", "json"]),
        "AWS Load Balancer Controller Deployment",
    )
    replicas = deployment.get("status", {}).get("replicas", 0)
    ready = deployment.get("status", {}).get("readyReplicas", 0)
    available = deployment.get("status", {}).get("availableReplicas", 0)
    require(isinstance(replicas, int) and replicas > 0 and ready == replicas and available == replicas, "ALB Controller Deployment is not fully available")


def verify_live_inputs(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_ROOT_PREFLIGHT") == OBSERVATION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_ROOT_PREFLIGHT={OBSERVATION_CONFIRMATION}",
    )
    expected_account = read_expected_account()
    validate_exact_main(expected_commit, git_runner)
    require(file_sha256(ROOT_SOURCE) == ROOT_SOURCE_SHA256, "aws-dev Root source identity changed")
    require(file_sha256(AWS_DEV_RELEASE) == AWS_DEV_RELEASE_SHA256, "aws-dev release identity changed")

    actual_account = read_runner(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    require(actual_account == expected_account, "AWS caller account does not match EXPECTED_AWS_ACCOUNT_ID")

    cluster = read_runner([
        "aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME,
        "--query", "cluster.[status,version,endpoint]", "--output", "text",
    ]).split()
    require(len(cluster) == 3, "EKS status/version/endpoint response is incomplete")
    require(cluster[0] == "ACTIVE", "aws-dev EKS cluster must be ACTIVE")

    state = [line for line in read_runner(["terraform", f"-chdir={TF_DIR}", "state", "list"]).splitlines() if line.strip()]
    require(len(state) == EXPECTED_STATE_ADDRESS_COUNT, "aws-dev Terraform state address count changed")
    require(any("aws_eks_cluster" in line for line in state), "aws-dev Terraform state has no EKS cluster address")

    kubernetes_server = read_runner(["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"])
    require(kubernetes_server == cluster[2], "kubectl context does not point to the reviewed aws-dev EKS cluster")
    require(read_runner(["kubectl", "get", "--raw=/readyz"]) == "ok", "Kubernetes /readyz is not ok")

    outputs = {
        name: terraform_output(read_runner, name)
        for name in (
            "vpc_id",
            "cnpg_backup_bucket_name",
            "cnpg_backup_role_arn",
            "external_secrets_role_arn",
            "external_secrets_secret_arn",
            "external_secrets_secret_name",
            "route53_hosted_zone_id",
        )
    }
    require(bool(VPC_RE.fullmatch(outputs["vpc_id"])), "Terraform VPC ID is malformed")
    require(bool(BUCKET_RE.fullmatch(outputs["cnpg_backup_bucket_name"])), "Terraform backup bucket name is malformed")
    for name in ("cnpg_backup_role_arn", "external_secrets_role_arn", "external_secrets_secret_arn"):
        require_arn_account(outputs[name], expected_account, name)

    secret = parse_json(
        read_runner([
            "aws", "secretsmanager", "describe-secret", "--region", AWS_REGION,
            "--secret-id", outputs["external_secrets_secret_arn"], "--output", "json",
        ]),
        "Secrets Manager container",
    )
    require(secret.get("ARN") == outputs["external_secrets_secret_arn"], "Secrets Manager ARN changed")
    require(secret.get("Name") == outputs["external_secrets_secret_name"], "Secrets Manager name changed")
    require(secret.get("DeletedDate") is None, "Secrets Manager container is pending deletion")

    zones = parse_json(
        read_runner(["aws", "route53", "list-hosted-zones-by-name", "--dns-name", "aureumstack.com", "--output", "json"]),
        "Route53 hosted-zone inventory",
    ).get("HostedZones")
    require(isinstance(zones, list), "Route53 hosted-zone inventory has no HostedZones")
    matching_zones = [
        zone for zone in zones
        if zone.get("Name") == "aureumstack.com." and zone.get("Config", {}).get("PrivateZone") is False
    ]
    require(len(matching_zones) == 1, "Exactly one public aureumstack.com hosted zone is required")
    observed_zone_id = str(matching_zones[0].get("Id", "")).removeprefix("/hostedzone/")
    require(observed_zone_id == outputs["route53_hosted_zone_id"], "Route53 hosted-zone ID does not match Terraform")

    verify_argocd(read_runner, outputs["vpc_id"])
    return {
        "control_plane_commit": expected_commit,
        "cluster_status": cluster[0],
        "cluster_version": cluster[1],
        "terraform_state_address_count": len(state),
        "kubernetes_readyz": "ok",
        "argocd_version": ARGOCD_VERSION,
        "argocd_workload_count": len(EXPECTED_ARGOCD_IMAGES),
        "alb_application_status": "Synced/Healthy",
        "root_application_present": False,
        "candidate_release_id": EXPECTED_RELEASE_ID,
    }


def run_deploy(expected_account: str) -> int:
    environment = os.environ.copy()
    environment.update(
        EXPECTED_AWS_ACCOUNT_ID=expected_account,
        AWS_REGION=AWS_REGION,
        CLUSTER_NAME=CLUSTER_NAME,
        TF_DIR=str(TF_DIR),
        ROOT_APPLICATION=ROOT_APPLICATION,
        SOURCE_FILE=str(ROOT_SOURCE),
        TARGET_REVISION="main",
        CONFIRM_AWS_DEV_ROOT_ENTRYPOINT=INTERNAL_ENTRYPOINT_CONFIRMATION,
    )
    result = subprocess.run([str(DEPLOY_ROOT)], cwd=ROOT, env=environment, check=False)
    return result.returncode


def validate_deployed_root(expected_commit: str, read_runner: ReadRunner) -> None:
    root = parse_json(
        read_runner(["kubectl", "-n", "argocd", "get", "application", ROOT_APPLICATION, "-o", "json"]),
        "aws-dev Root Application",
    )
    source = root.get("spec", {}).get("source", {})
    require(source.get("repoURL") == "https://github.com/SterlingAureum/startup-devops-baseline.git", "Root repository changed")
    require(source.get("targetRevision") == "main", "Root targetRevision must remain main")
    require(source.get("path") == "clusters/aws/overlays/dev", "Root source path changed")
    require(root.get("status", {}).get("sync", {}).get("status") == "Synced", "Root Application is not Synced")
    require(root.get("status", {}).get("health", {}).get("status") == "Healthy", "Root Application is not Healthy")
    require(root.get("status", {}).get("sync", {}).get("revision") == expected_commit, "Root Application did not resolve the reviewed main commit")


def verification_result(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-root-deploy-inputs-verified",
        **inventory,
        "execution_authorized": False,
        "read_only_checks": [
            "clean-exact-remote-main",
            "root-and-release-file-identities",
            "aws-caller-and-eks-identity",
            "terraform-state-and-root-outputs",
            "kubernetes-context-and-readyz",
            "secrets-manager-container",
            "route53-public-zone",
            "argocd-workloads-and-alb-application",
            "root-application-absence",
        ],
        "next_action": "obtain-separate-root-application-deploy-approval",
    }


def execute(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
    deploy_runner: DeployRunner = run_deploy,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_ROOT_DEPLOY") == EXECUTION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_ROOT_DEPLOY={EXECUTION_CONFIRMATION}",
    )
    inventory = verify_live_inputs(expected_commit, git_runner, read_runner)
    expected_account = read_expected_account()
    return_code = deploy_runner(expected_account)
    if return_code != 0:
        raise CommandFailure(
            f"aws-dev Root deployment exited {return_code}; do not rerun, promote or destroy before partial-state review"
        )
    validate_exact_main(expected_commit, git_runner)
    validate_deployed_root(expected_commit, read_runner)
    return {
        "status": "aws-dev-root-application-deploy-complete",
        "control_plane_commit": expected_commit,
        "candidate_release_id": inventory["candidate_release_id"],
        "root_application": ROOT_APPLICATION,
        "root_target_revision": "main",
        "root_resolved_revision": expected_commit,
        "root_application_synced": True,
        "root_application_healthy": True,
        "database_and_secret_bootstrap_complete": True,
        "demo_application_accepted_health": True,
        "stable_dns_reconciled": True,
        "runtime_qualified": False,
        "progressive_delivery_promoted": False,
        "traffic_generated": False,
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
        parser.exit(1, f"aws-dev Root deployment stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
