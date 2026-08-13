#!/usr/bin/env python3
"""Offline structural validation for the v0.10.3 trusted runtime boundary."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def read(root: Path, relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing trusted runtime file: {relative}")
    return path.read_text()


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    contract = json.loads(read(root, "delivery/contracts/runtime-executor.json"))
    schema = json.loads(read(root, "delivery/contracts/runtime-qualification.schema.json"))
    app = json.loads(read(root, "delivery/contracts/demo-api.json"))

    require(contract["schemaVersion"] == "v0.10.5", "Bad runtime contract version")
    require(contract["application"] == "demo-api", "Bad runtime application")
    require(set(contract["environments"]) == {"aws-dev", "aws-test"}, "Runtime environments must be dev/test only")
    require(contract["production"] == {
        "enabled": False,
        "environment": "aws-prod",
        "automaticQualification": False,
    }, "Production runtime boundary changed")
    require(contract["controlPlane"]["allowedRef"] == "refs/heads/main", "Runtime ref must be protected main")
    require(contract["controlPlane"]["allowPullRequestCode"] is False, "PR code cannot reach runtime")
    require(contract["controlPlane"]["automaticEnvironmentCreation"] is False, "Runtime cannot create EKS")
    require(contract["executor"]["kind"] == "ephemeral-self-hosted", "Runtime executor must be ephemeral")
    require(contract["executor"]["fallbackToGitHubHosted"] is False, "GitHub-hosted EKS fallback is forbidden")
    require(contract["executor"]["persistentAwsCredentials"] is False, "Persistent AWS credentials are forbidden")
    require(contract["executor"]["requiredLabels"] == ["self-hosted", "linux", "x64", "trusted-runtime"], "Runner labels changed")
    require(contract["awsPermissions"]["allowedActions"] == ["sts:GetCallerIdentity", "eks:DescribeCluster"], "AWS permissions widened")
    require(contract["kubernetesPermissions"]["verbs"] == ["get", "list", "watch"], "Kubernetes verbs widened")
    require(set(contract["kubernetesPermissions"]["forbiddenResources"]) == {"secrets", "pods/exec"}, "Kubernetes deny boundary changed")
    require(contract["forbiddenInputs"] == ["cluster_name", "namespace", "argo_application", "https_url", "role_arn"], "Forbidden target inputs changed")
    require(contract["artifact"]["allowCredentials"] is False and contract["artifact"]["allowKubeconfig"] is False, "Artifact may expose credentials")
    require(contract["convergenceWait"] == {
        "maximumSeconds": 900,
        "intervalSeconds": 15,
        "passiveOnly": True,
        "argoSyncAllowed": False,
        "rolloutMutationAllowed": False,
    }, "Runtime convergence wait boundary changed")
    for name, expected in {
        "aws-dev": ("aws-dev-runtime", "startup-devops-baseline-dev", "Deployment"),
        "aws-test": ("aws-test-runtime", "startup-devops-baseline-test", "Rollout"),
    }.items():
        value = contract["environments"][name]
        require((value["githubEnvironment"], value["clusterName"], value["workloadKind"]) == expected, f"{name} identity changed")
        require(value["oidcSubject"] == f"repo:SterlingAureum/startup-devops-baseline:environment:{name}-runtime", f"{name} OIDC subject changed")

    require(schema["properties"]["environment"]["enum"] == ["aws-dev", "aws-test"], "Result schema permits an unsafe environment")
    require(schema["properties"]["status"]["enum"] == ["qualified", "blocked", "failed"], "Result statuses changed")
    require(app["schemaVersion"] == "v0.10.7", "Application contract is not on v0.10.7")
    require(app["application"]["runtimeExecutorContract"] == "delivery/contracts/runtime-executor.json", "Application contract does not link runtime executor")
    require(app["application"]["runtimeQualificationWorkflow"] == contract["workflow"], "Workflow link differs from runtime contract")
    trusted = app["executionBoundaries"]["trustedRuntime"]
    require(trusted["implementedEnvironments"] == ["aws-dev", "aws-test"], "Application runtime environments changed")
    require(trusted["productionAccess"] is False, "Application contract enabled production runtime")

    workflow = read(root, contract["workflow"])
    require("\n  workflow_dispatch:\n" in workflow and "\n  workflow_call:\n" in workflow, "Runtime workflow must retain manual and reusable entrypoints")
    require(not re.search(r"(?m)^  (pull_request|pull_request_target|schedule):", workflow), "Untrusted or scheduled runtime trigger is forbidden")
    for required_input in contract["inputs"]:
        require(workflow.count(f"      {required_input}:\n") == 2, f"Runtime input {required_input} must exist in both entrypoints")
    for forbidden_input in contract["forbiddenInputs"]:
        require(f"      {forbidden_input}:\n" not in workflow, f"Workflow accepts arbitrary target input: {forbidden_input}")
    require("aws-prod" not in workflow, "Runtime workflow must not permit aws-prod")
    preflight, qualify = workflow.split("\n  qualify:\n", 1)
    require("runs-on: ubuntu-latest" in preflight, "Preflight must use a GitHub-hosted read-only runner")
    require("configure-aws-credentials" not in preflight and "kubectl" not in preflight, "Preflight acquired runtime access")
    require('runs-on: [self-hosted, linux, x64, trusted-runtime, "${{ inputs.environment }}"]' in qualify, "Runtime job does not require trusted environment labels")
    require("runs-on: ubuntu-latest" not in qualify, "Runtime job fell back to GitHub-hosted")
    require("name: ${{ inputs.environment }}-runtime" in qualify and "deployment: false" in qualify, "GitHub Environment boundary is missing")
    require("id-token: write" in qualify and "contents: read" in qualify, "Runtime job lacks minimal OIDC permissions")
    require("contents: write" not in workflow and "pull-requests: write" not in workflow, "Runtime workflow gained Git write permission")
    require("GITHUB_REF" in preflight and "refs/heads/main" in preflight, "Protected-main caller check is missing")
    require("steps.aws.outcome != 'success'" in qualify and "oidc_denied" in qualify, "OIDC failure is not classified")
    require("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in qualify, "Runtime artifact action pin changed")
    require("aws-actions/configure-aws-credentials@e6de054238d6b7531b4efff3b6587d9aade6a06c" in qualify, "AWS credential action pin changed")
    require("${{ runner.temp }}/runtime-qualification/result.json" in qualify, "Artifact is not restricted to the result JSON")

    collector = read(root, "scripts/collect-demo-api-runtime-qualification-aws.sh")
    require("aws-prod" not in collector, "Collector permits production")
    require("ResourceNotFoundException" in collector and "environment_absent" in collector, "Absent environment is not classified")
    require("endpoint_unreachable" in collector and "main_advanced" in collector, "Recoverable runtime waits are incomplete")
    require("kubectl auth can-i" in collector and "rbac_boundary_failed" in collector, "RBAC negative checks are missing")
    require("imageID" in collector and "EXPECTED_IMAGE_DIGEST" in collector, "Pod imageID is not release-bound")
    require("WAIT_TIMEOUT_SECONDS:-900" in collector and "WAIT_INTERVAL_SECONDS:-15" in collector, "Bounded convergence wait is missing")
    require("sleep \"${WAIT_INTERVAL_SECONDS}\"" in collector, "Passive convergence polling is missing")
    for line in collector.splitlines():
        if "kubectl auth can-i" in line:
            continue
        require(not re.search(r"\bkubectl\b.*\b(apply|create|delete|edit|exec|patch|replace|rollout)\b", line), "Collector contains a Kubernetes mutation")
        require(not re.search(r"\b(terraform\s+apply|git\s+commit|git\s+push|gh\s+pr)\b", line), "Collector contains an external mutation")

    module = read(root, "infra/terraform/aws/modules/github-actions-runtime-identity/main.tf")
    variables = read(root, "infra/terraform/aws/modules/github-actions-runtime-identity/variables.tf")
    require('"token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"' in module, "OIDC audience is not exact")
    require('"token.actions.githubusercontent.com:sub" = local.oidc_subject' in module, "OIDC subject is not exact")
    require("repo:*" not in module and "StringLike" not in module, "OIDC trust uses a wildcard")
    actions = set(re.findall(r'"((?:sts|eks):[A-Za-z*]+)"', module))
    require(actions == {"sts:AssumeRoleWithWebIdentity", "sts:GetCallerIdentity", "eks:DescribeCluster"}, f"Unexpected IAM actions: {sorted(actions)}")
    require("Resource = var.cluster_arn" in module, "EKS permission is not exact-cluster scoped")
    require('kubernetes_groups = [local.kubernetes_group]' in module, "EKS access entry does not map custom RBAC")
    require('["aws-dev", "aws-test"]' in variables, "Terraform module permits an unsafe environment")
    for environment in ("dev", "test"):
        main_tf = read(root, f"infra/terraform/aws/environments/{environment}/main.tf")
        require('source = "../../modules/github-actions-runtime-identity"' in main_tf, f"{environment} runtime module missing")
        require(f'environment              = "aws-{environment}"' in main_tf, f"{environment} runtime module identity changed")
    require("github_actions_runtime_identity" not in read(root, "infra/terraform/aws/environments/prod/main.tf"), "Production runtime identity must not exist")

    rbac = read(root, "clusters/aws/base/security/runtime-qualification/rbac.yaml")
    require('verbs: ["get", "list", "watch"]' in rbac, "Read-only RBAC verbs are missing")
    require(not re.search(r'verbs:\s*\[[^\]]*(create|update|patch|delete|\*)', rbac), "RBAC contains a write or wildcard verb")
    require(not re.search(r'resources:\s*\[[^\]]*(secrets|pods/exec|\*)', rbac), "RBAC exposes a sensitive or wildcard resource")
    application_resource = "../../base/platform/runtime-qualification-rbac"
    for environment in ("dev", "test"):
        overlay = read(root, f"clusters/aws/overlays/{environment}/kustomization.yaml")
        require(
            re.search(rf"(?m)^  - {re.escape(application_resource)}$", overlay),
            f"{environment} RBAC Application directory missing",
        )
        require(
            not re.search(r"(?m)^\s*- .*runtime-qualification-rbac(?:\.yaml|/[^\s]+)$", overlay),
            f"{environment} directly loads an out-of-root RBAC Application file",
        )
    require(
        "runtime-qualification-rbac" not in read(root, "clusters/aws/overlays/prod/kustomization.yaml"),
        "Production overlay received runtime RBAC",
    )
    legacy_application = root / "clusters/aws/base/platform/runtime-qualification-rbac.yaml"
    require(not legacy_application.exists(), "Legacy cross-root RBAC Application file remains")
    rbac_application_kustomization = read(
        root,
        "clusters/aws/base/platform/runtime-qualification-rbac/kustomization.yaml",
    )
    require(
        re.search(r"(?m)^  - application\.yaml$", rbac_application_kustomization),
        "Runtime RBAC Application Kustomization does not load application.yaml",
    )
    rbac_application = read(root, "clusters/aws/base/platform/runtime-qualification-rbac/application.yaml")
    require("targetRevision: main" in rbac_application, "Runtime RBAC Application is not main-sourced")
    require("path: clusters/aws/base/security/runtime-qualification" in rbac_application, "Runtime RBAC Application path changed")

    writer = read(root, "scripts/write-demo-api-runtime-qualification.py")
    require("SENSITIVE_KEY" in writer and "reject_sensitive_keys" in writer, "Result writer lacks secret-field rejection")
    require("aws-prod" not in writer, "Result writer permits production")

    print("trusted runtime executor structure passed")


if __name__ == "__main__":
    main()
