#!/usr/bin/env python3
"""Verify or execute the separately reviewed aws-test GitOps bootstrap."""

from __future__ import annotations

import argparse
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
BASELINE_MAIN = "8ff28f9f047d866c494db04cf71333efcdfe1f34"
APPLIED_MAIN = "1376129d42c6dbc19ffb57c97244d2b31ddd4ff7"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-test"
SECRET_NAME = "startup-devops-baseline-test/demo-api/postgresql"
ROOT_APPLICATION = "startup-devops-aws-test-root"
ALB_APPLICATION = "aws-load-balancer-controller"
TF_DIR = ROOT / "infra/terraform/aws/environments/test"
STATE_PATH = TF_DIR / "terraform.tfstate"
BOOTSTRAP = ROOT / "scripts/bootstrap-eks-argocd.sh"
EVIDENCE = ROOT / "delivery/contracts/v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence.json"
PRIVATE_PLAN_SHA256 = "70a3899c8475552b2bf155e287477e7f81091e3cee9cfb01deb7932e3c449be8"
STATE_SHA256 = "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b"
EVIDENCE_SHA256 = "6ff2fef31b72a513289fcb1a20204545012ddd24fbdb37ccc5806789686ab56f"
BOOTSTRAP_SHA256 = "e849aa6b6e9cf688c8425c8670cb67dba00e2c794b481c83c9f89570c1d2f37f"
ROOT_APPLICATION_SHA256 = "3a0d0d15c03524d6255019bec7591b2b00b514f08e394582d34ce3a42ce2c5e4"
ARGOCD_VERSION = "v3.5.2"
SESSION_DEADLINE_UTC = "2026-09-12T17:38:53Z"
MINIMUM_REMAINING_SECONDS = 900
OBSERVATION_CONFIRMATION = "observe-reviewed-aws-test-gitops-bootstrap"
EXECUTION_CONFIRMATION = "bootstrap-reviewed-aws-test-gitops"

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int], subprocess.CompletedProcess[bytes]]


class CommandFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_private_directory(path: Path, label: str) -> None:
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a directory")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, f"{label} mode must be 700")


def require_private_file(path: Path, expected: str, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 600")
    require_private_directory(path.parent, f"{label} parent")
    require(sha256(path) == expected, f"{label} fingerprint changed")


def require_repository_file(path: Path, expected: str, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    require(sha256(path) == expected, f"{label} fingerprint changed")


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


def safe_environment(account_id: str) -> dict[str, str]:
    allowed = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
        "KUBECONFIG",
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
        CLUSTER_NAME=CLUSTER_NAME,
        TF_DIR=str(TF_DIR),
        ARGOCD_VERSION=ARGOCD_VERSION,
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(content)
    path.chmod(0o600)


def invoke(
    arguments: list[str], environment: dict[str, str], timeout: int,
    runner: CommandRunner, output: Path | None = None, label: str | None = None,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, timeout)
    if output is not None:
        require(label is not None, "Private command label is required")
        write_private(output / f"{label}.stdout", result.stdout)
        write_private(output / f"{label}.stderr", result.stderr)
    if result.returncode and not allow_failure:
        raise CommandFailure(f"{label or arguments[0]} failed; preserve Terraform state and private evidence")
    return result


def parse_json(result: subprocess.CompletedProcess[bytes], label: str) -> Any:
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"{label} output is invalid") from error


def require_absent(result: subprocess.CompletedProcess[bytes], label: str) -> None:
    combined = result.stdout + result.stderr
    absence_markers = (
        b"NotFound",
        b"doesn't have a resource type",
        b"could not find the requested resource",
    )
    require(
        result.returncode != 0 and any(marker in combined for marker in absence_markers),
        f"{label} must be absent",
    )


def verify_inputs(
    expected_main: str, private_plan: Path, private_output: Path,
    repository_root: Path = ROOT, git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    require(re.fullmatch(r"[0-9a-f]{40}", expected_main) is not None, "Expected main must be a full SHA")
    require(expected_main != BASELINE_MAIN, "Bootstrap requires the post-merge protected main")
    require(git_runner(["branch", "--show-current"]) == "main", "Bootstrap must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Bootstrap requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal expected main",
    )
    git_runner(["merge-base", "--is-ancestor", BASELINE_MAIN, expected_main])

    require_repository_file(repository_root / EVIDENCE.relative_to(ROOT), EVIDENCE_SHA256, "Apply/resume evidence")
    require_repository_file(repository_root / BOOTSTRAP.relative_to(ROOT), BOOTSTRAP_SHA256, "Shared bootstrap")
    require_repository_file(
        repository_root / "clusters/aws/overlays/test/root-app.yaml",
        ROOT_APPLICATION_SHA256,
        "aws-test Root Application",
    )
    require_private_file(private_plan, PRIVATE_PLAN_SHA256, "Private creation plan")
    plan = json.loads(private_plan.read_text())
    account = plan.get("aws_account_id")
    management_ipv4 = plan.get("management_ipv4")
    release = plan.get("candidate", {}).get("release_id")
    require(isinstance(account, str) and re.fullmatch(r"[0-9]{12}", account) is not None, "Private account is invalid")
    require(isinstance(management_ipv4, str) and management_ipv4, "Private management address is invalid")
    require(release == "demo-api-cf0a6bcbc466-cdffd3d71763", "Candidate release changed")

    state_path = repository_root / STATE_PATH.relative_to(ROOT)
    require(state_path.is_file() and not state_path.is_symlink(), "Terraform state must be a regular file")
    require(stat.S_IMODE(state_path.stat().st_mode) == 0o600, "Terraform state mode must be 600")
    require(sha256(state_path) == STATE_SHA256, "Terraform state fingerprint changed")
    require_private_directory(private_output.parent, "Bootstrap output parent")
    require(not private_output.exists() and not private_output.is_symlink(), "Bootstrap output must be new")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    deadline = datetime.fromisoformat(SESSION_DEADLINE_UTC.replace("Z", "+00:00"))
    remaining = int((deadline - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "At least 900 seconds must remain before teardown review")
    return {
        "expected_main": expected_main,
        "account_id": account,
        "management_cidr": f"{management_ipv4}/32",
        "release_id": release,
        "state_path": state_path,
        "remaining": remaining,
    }


def live_checks(
    context: dict[str, Any], runner: CommandRunner = run_command,
    output: Path | None = None, post_bootstrap: bool = False,
) -> dict[str, Any]:
    environment = safe_environment(context["account_id"])
    phase_prefix = "post-bootstrap" if post_bootstrap else "immediate-preflight"

    def call(label: str, arguments: list[str], timeout: int = 120, allow_failure: bool = False):
        private_label = f"{phase_prefix}-{label}" if output is not None else label
        return invoke(arguments, environment, timeout, runner, output, private_label, allow_failure)

    caller = parse_json(call("sts-caller-identity", ["aws", "sts", "get-caller-identity", "--output", "json"]), "STS")
    require(caller.get("Account") == context["account_id"], "AWS account changed")
    inventory = parse_json(call("eks-list-clusters", ["aws", "eks", "list-clusters", "--region", AWS_REGION, "--output", "json"]), "EKS inventory")
    clusters = inventory.get("clusters")
    require(isinstance(clusters, list), "EKS inventory is invalid")
    rehearsal = set(clusters) & {"startup-devops-baseline-dev", CLUSTER_NAME, "startup-devops-baseline-prod"}
    require(rehearsal == {CLUSTER_NAME}, "Expected only the aws-test rehearsal cluster")
    described = parse_json(call("eks-describe-cluster", ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"]), "EKS cluster")
    cluster = described.get("cluster", {})
    require(cluster.get("name") == CLUSTER_NAME and cluster.get("status") == "ACTIVE", "aws-test EKS cluster is not ACTIVE")
    require(cluster.get("resourcesVpcConfig", {}).get("publicAccessCidrs") == [context["management_cidr"]], "EKS public CIDR changed")
    endpoint = cluster.get("endpoint")
    require(isinstance(endpoint, str) and endpoint.startswith("https://"), "EKS endpoint is invalid")

    secret = parse_json(call("secret-metadata", ["aws", "secretsmanager", "describe-secret", "--region", AWS_REGION, "--secret-id", SECRET_NAME, "--output", "json"]), "Secret metadata")
    require(secret.get("Name") == SECRET_NAME and "DeletedDate" not in secret, "Secret metadata is absent or pending deletion")
    state_list = call("terraform-state-list", ["terraform", f"-chdir={TF_DIR}", "state", "list"])
    require(len([line for line in state_list.stdout.decode().splitlines() if line]) == 103, "Terraform state address count changed")
    config = parse_json(call("kubectl-config-view", ["kubectl", "config", "view", "--minify", "-o", "json"]), "kubeconfig")
    config_clusters = config.get("clusters", [])
    require(len(config_clusters) == 1 and config_clusters[0].get("cluster", {}).get("server") == endpoint, "kubeconfig does not target reviewed aws-test")
    ready = call("kubectl-readyz", ["kubectl", "get", "--raw=/readyz"])
    require(ready.stdout.strip() == b"ok", "Kubernetes API is not ready")

    alb_role = call("terraform-output-alb-role", ["terraform", f"-chdir={TF_DIR}", "output", "-raw", "aws_load_balancer_controller_role_arn"]).stdout.decode().strip()
    karpenter_role = call("terraform-output-karpenter-role", ["terraform", f"-chdir={TF_DIR}", "output", "-raw", "karpenter_controller_role_arn"]).stdout.decode().strip()
    role_pattern = re.compile(rf"^arn:aws:iam::{context['account_id']}:role/[A-Za-z0-9+=,.@_/-]+$")
    require(bool(role_pattern.fullmatch(alb_role)) and bool(role_pattern.fullmatch(karpenter_role)), "Terraform role output changed")

    if not post_bootstrap:
        for label, arguments in (
            ("argocd-namespace-before", ["kubectl", "get", "namespace", "argocd", "-o", "json"]),
            ("alb-service-account-before", ["kubectl", "get", "serviceaccount", "aws-load-balancer-controller", "-n", "kube-system", "-o", "json"]),
            ("karpenter-service-account-before", ["kubectl", "get", "serviceaccount", "karpenter", "-n", "kube-system", "-o", "json"]),
        ):
            require_absent(call(label, arguments, allow_failure=True), label)
    else:
        namespace = parse_json(call("argocd-namespace-after", ["kubectl", "get", "namespace", "argocd", "-o", "json"]), "Argo CD namespace")
        require(namespace.get("metadata", {}).get("name") == "argocd", "Argo CD namespace missing")
        for name, expected_role in (("aws-load-balancer-controller", alb_role), ("karpenter", karpenter_role)):
            service_account = parse_json(call(f"{name}-service-account-after", ["kubectl", "get", "serviceaccount", name, "-n", "kube-system", "-o", "json"]), name)
            annotation = service_account.get("metadata", {}).get("annotations", {}).get("eks.amazonaws.com/role-arn")
            require(annotation == expected_role, f"{name} role annotation changed")
        for label, kind, name in (
            ("argocd-server-after", "deployment", "argocd-server"),
            ("argocd-repo-server-after", "deployment", "argocd-repo-server"),
            ("argocd-controller-after", "statefulset", "argocd-application-controller"),
        ):
            workload = parse_json(call(label, ["kubectl", "get", kind, name, "-n", "argocd", "-o", "json"]), label)
            require(workload.get("status", {}).get("readyReplicas", 0) >= 1, f"{name} is not ready")
        alb = parse_json(call("alb-application-after", ["kubectl", "get", "application", ALB_APPLICATION, "-n", "argocd", "-o", "json"]), "ALB Application")
        require(alb.get("metadata", {}).get("name") == ALB_APPLICATION, "ALB Application missing")

    root = call("root-application", ["kubectl", "get", "application", ROOT_APPLICATION, "-n", "argocd", "-o", "json"], allow_failure=True)
    require_absent(root, "aws-test Root Application")
    return {"alb_role": alb_role, "karpenter_role": karpenter_role}


def verify_phase(context: dict[str, Any], runner: CommandRunner = run_command) -> dict[str, Any]:
    require(os.environ.get("AWS_ENVIRONMENT") == "aws-test", "AWS_ENVIRONMENT must be aws-test")
    require(os.environ.get("EXPECTED_AWS_ACCOUNT_ID") == context["account_id"], "Expected account must match private evidence")
    require(os.environ.get("CONFIRM_AWS_TEST_GITOPS_BOOTSTRAP_PREFLIGHT") == OBSERVATION_CONFIRMATION, "Bootstrap observation confirmation missing")
    live_checks(context, runner)
    return {
        "status": "aws-test-gitops-bootstrap-inputs-verified",
        "control_plane_commit": context["expected_main"],
        "applied_control_plane_commit": APPLIED_MAIN,
        "candidate_release_id": context["release_id"],
        "reviewed_apply_resume_evidence_sha256": EVIDENCE_SHA256,
        "terraform_state_sha256": STATE_SHA256,
        "state_address_count": 103,
        "eks_cluster_active": True,
        "argocd_namespace_absent": True,
        "root_application_absent": True,
        "remaining_session_seconds": context["remaining"],
        "gitops_bootstrap_authorized": False,
        "terraform_command_executed": False,
        "kubernetes_mutation_executed": False,
        "next_action": "obtain-separate-aws-test-gitops-bootstrap-approval",
    }


def execute_phase(
    context: dict[str, Any], private_output: Path, reviewed_verify: Path,
    expected_verify_sha256: str, runner: CommandRunner = run_command,
) -> dict[str, Any]:
    require_private_file(reviewed_verify, expected_verify_sha256, "Reviewed bootstrap verify")
    verify_doc = json.loads(reviewed_verify.read_text())
    require(verify_doc.get("status") == "aws-test-gitops-bootstrap-inputs-verified", "Reviewed verify status changed")
    require(verify_doc.get("control_plane_commit") == context["expected_main"], "Reviewed verify main changed")
    require(os.environ.get("AWS_ENVIRONMENT") == "aws-test", "AWS_ENVIRONMENT must be aws-test")
    require(os.environ.get("EXPECTED_AWS_ACCOUNT_ID") == context["account_id"], "Expected account must match private evidence")
    require(os.environ.get("CONFIRM_AWS_TEST_GITOPS_BOOTSTRAP_PREFLIGHT") == OBSERVATION_CONFIRMATION, "Bootstrap observation confirmation missing")
    require(os.environ.get("CONFIRM_AWS_TEST_GITOPS_BOOTSTRAP_EXECUTION") == EXECUTION_CONFIRMATION, "Bootstrap execution confirmation missing")
    for forbidden in (
        "CONFIRM_AWS_TEST_BOOTSTRAP", "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION",
        "CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION", "CONFIRM_AWS_TEST_APPLY",
        "CONFIRM_AWS_ENVIRONMENT_DESTROY", "AWS_TEST_APPLY_MODE",
    ):
        require(not os.environ.get(forbidden), "Legacy, Terraform and destroy controls must be unset")

    private_output.mkdir(mode=0o700)
    private_output.chmod(0o700)
    live_checks(context, runner, private_output, post_bootstrap=False)
    state_before = sha256(context["state_path"])
    bootstrap = invoke(
        [str(BOOTSTRAP)], safe_environment(context["account_id"]), 1800,
        runner, private_output, "gitops-bootstrap",
    )
    require(bootstrap.returncode == 0, "GitOps bootstrap failed")
    live_checks(context, runner, private_output, post_bootstrap=True)
    require(sha256(context["state_path"]) == state_before == STATE_SHA256, "Terraform state changed during bootstrap")
    return {
        "status": "aws-test-gitops-bootstrap-complete",
        "control_plane_commit": context["expected_main"],
        "applied_control_plane_commit": APPLIED_MAIN,
        "candidate_release_id": context["release_id"],
        "reviewed_verify_sha256": expected_verify_sha256,
        "reviewed_apply_resume_evidence_sha256": EVIDENCE_SHA256,
        "terraform_state_sha256": STATE_SHA256,
        "argocd_version": ARGOCD_VERSION,
        "gitops_bootstrap_executed": True,
        "root_application_deployed": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed": False,
        "terraform_destroy_executed": False,
        "automatic_retry_performed": False,
        "traffic_generated": False,
        "qualification_executed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-separate-aws-test-root-application-deploy",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    parser.add_argument("--private-plan", required=True, type=Path)
    parser.add_argument("--private-output-directory", required=True, type=Path)
    parser.add_argument("--reviewed-verify-result", type=Path)
    parser.add_argument("--expected-verify-sha256")
    args = parser.parse_args()
    try:
        context = verify_inputs(
            args.expected_control_plane_commit, args.private_plan,
            args.private_output_directory,
        )
        if args.phase == "verify":
            require(args.reviewed_verify_result is None and args.expected_verify_sha256 is None, "Verify does not accept execution evidence")
            result = verify_phase(context)
        else:
            require(args.reviewed_verify_result is not None, "Reviewed verify result is required")
            require(re.fullmatch(r"[0-9a-f]{64}", args.expected_verify_sha256 or "") is not None, "Expected verify SHA-256 is required")
            result = execute_phase(
                context, args.private_output_directory, args.reviewed_verify_result,
                args.expected_verify_sha256,
            )
    except (
        CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError,
        subprocess.TimeoutExpired, UnicodeDecodeError, ValueError,
    ) as error:
        parser.exit(1, f"aws-test GitOps bootstrap stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
