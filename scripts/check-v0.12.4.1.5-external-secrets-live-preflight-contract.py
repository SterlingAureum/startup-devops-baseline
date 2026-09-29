#!/usr/bin/env python3
"""Validate the External Secrets 2.9.0 live-preflight contract offline."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
from typing import Any


class LivePreflightContractError(ValueError):
    """Raised when a reviewed live-preflight boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LivePreflightContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_executable_worktree_mode(mode: int, label: str) -> None:
    require(stat.S_ISREG(mode), f"{label} worktree file type drift")
    require(bool(mode & stat.S_IXUSR), f"{label} owner-executable bit missing")


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.5-external-secrets-live-preflight-contract-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5", "version drift")
    require(value.get("status") == "external-secrets-2.9.0-live-preflight-contract-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "7c29e7836270390197754240b38b249ebe1794a4", "baseline drift")
    require(value.get("designedAtDate") == "2026-09-29", "design date drift")

    require(value.get("boundPredecessors") == {
        "artifactRenderProofPath": "delivery/contracts/v0.12.4.1.3-external-secrets-artifact-render-proof.json",
        "artifactRenderProofSha256": "fc1f8923376e1bc6f3bd20b6f5e9ee33f3b221ad601888b4c231c5951939dd84",
        "firstHopPlanPath": "delivery/contracts/v0.12.4.1.4-external-secrets-2.9.0-hop-plan.json",
        "firstHopPlanSha256": "b955c94eff8e3ac8541263f4c2f5da51ee9404ce862c7aef7ed59afc38ef2ff5",
    }, "predecessor binding drift")
    require(value.get("target") == {
        "environment": "aws-dev",
        "region": "us-east-1",
        "clusterName": "startup-devops-baseline-dev",
        "kubernetesMinor": "1.36",
        "operatorApplication": "external-secrets",
        "resourceApplication": "external-secrets-startup-apps",
        "currentChartVersion": "2.8.0",
        "candidateChartVersion": "2.9.0",
        "candidateChartSha256": "da2d5c126a103b4c1b16a9dc1c168c4332a3687144e88ac070e594f81a0b6578",
        "candidateRenderSha256": "880e6805213cf77cd89cf0e60e03624bc01c74d23a2c61693a1be2a5ce2ca8bb",
        "candidateRenderObjectCount": 37,
    }, "target identity drift")
    require(value.get("privateRequest") == {
        "schemaVersion": "v0.12.4.1.5-external-secrets-live-preflight-request-v1",
        "operation": "run-reviewed-external-secrets-2.9.0-live-preflight",
        "maximumApprovalWindowSeconds": 3600,
        "minimumRemainingApprovalSeconds": 900,
        "requestMustBeOutsideRepository": True,
        "requestMode": "0600",
        "requestParentMode": "0700",
        "artifactFilesMustBeOutsideRepository": True,
        "artifactFileMode": "0600",
        "outputDirectoryMustBeNew": True,
        "outputParentMode": "0700",
    }, "private request boundary drift")
    require(value.get("verifyPhase") == {
        "protectedMainMustBeExactAndClean": True,
        "headAndOriginMainMustEqualRequestCommit": True,
        "predecessorDigestsMustMatch": True,
        "repositoryPinMustRemainTwoEight": True,
        "privateChartAndRenderDigestsMustMatch": True,
        "approvalMustBeCurrentlyActive": True,
        "awsCommandsAllowed": False,
        "kubectlCommandsAllowed": False,
        "helmCommandsAllowed": False,
        "operationalCommandsExecuted": [],
    }, "verify phase drift")

    execute = value.get("executePhase")
    require(isinstance(execute, dict) and len(execute) == 12, "execute phase shape drift")
    require(execute.get("requiredConfirmationVariable") == "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT", "confirmation variable drift")
    require(execute.get("requiredConfirmationValue") == "run-reviewed-external-secrets-2.9.0-live-preflight", "confirmation value drift")
    require(execute.get("awsReadCommands") == ["sts-get-caller-identity", "eks-describe-cluster"], "AWS read inventory drift")
    require(execute.get("kubernetesReadTargets") == [
        "readyz", "argocd-applications", "external-secrets-deployments",
        "external-secrets-serviceaccount", "external-secrets-rbac",
        "repository-used-crds", "secretstore", "externalsecret",
    ], "Kubernetes read inventory drift")
    require(execute.get("serverSideDryRunCommandShape") == "kubectl apply --server-side --dry-run=server --field-manager=v0.12.4.1.5-external-secrets-preflight -o name -f <private-verified-2.9.0-render.yaml>", "dry-run command drift")
    require(execute.get("serverSideDryRunRunsExactlyOnce") is True, "dry-run cardinality weakened")
    require(execute.get("serverSideDryRunStderrMustBeEmpty") is True, "dry-run stderr boundary weakened")
    require(execute.get("serverSideDryRunObjectCount") == 37, "dry-run object count drift")
    require(execute.get("preAndPostProtectedProjectionMustMatch") is True, "projection gate weakened")
    require(execute.get("rawOutputsRemainPrivate") is True, "private evidence boundary weakened")
    require(execute.get("commandTimeoutSeconds") == 120, "command timeout drift")
    require(execute.get("automaticRetry") is False, "automatic retry enabled")

    assertions = value.get("liveAssertions")
    require(isinstance(assertions, dict) and len(assertions) == 14, "live assertion inventory drift")
    require(all(assertion is True for assertion in assertions.values()), "live assertion weakened")
    require(value.get("secretBoundary") == {
        "awsGetSecretValueAllowed": False,
        "kubernetesSecretGetAllowed": False,
        "targetSecretDataAllowed": False,
        "secretValueDigestAllowed": False,
        "remoteSecretKeyMayAppearOnlyInPrivateEvidence": True,
        "publicResultContainsResourceIdentity": False,
    }, "secret boundary drift")
    require(value.get("forbiddenOperations") == [
        "git-mutation", "github-pull-request-mutation", "argocd-sync-or-refresh",
        "kubectl-diff", "non-dry-run-kubectl-apply", "kubectl-patch-annotate-delete-or-replace",
        "helm-install-or-upgrade", "aws-mutation", "secret-value-read",
        "automatic-retry", "automatic-rollback",
    ], "forbidden operation inventory drift")
    require(value.get("resultBoundary") == {
        "privateRawCommandEvidenceRequired": True,
        "privateEvidenceMode": "0600",
        "redactedResultMayContainOnlyBooleansCountsVersionsAndDigests": True,
        "preflightSuccessAuthorizesGitPinMutation": False,
        "preflightSuccessRequiresSeparateHumanReview": True,
        "failureMustPreservePrivateEvidence": True,
        "failureMayBeRetriedWithoutNewRequest": False,
    }, "result boundary drift")
    require(value.get("executionBoundary") == {
        "publicArtifactDownloadAuthorized": False,
        "awsReadAuthorizedAfterSeparateApproval": True,
        "awsMutationAuthorized": False,
        "kubernetesReadAuthorizedAfterSeparateApproval": True,
        "kubernetesServerDryRunAuthorizedAfterSeparateApproval": True,
        "kubernetesPersistentMutationAuthorized": False,
        "gitVersionMutationAuthorized": False,
        "githubPullRequestMutationAuthorized": False,
        "argocdOperationAuthorized": False,
        "helmOperationAuthorized": False,
        "secretValueReadAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
    }, "execution authority drift")
    require(value.get("overallGate") == {
        "status": "blocked-awaiting-private-request-verification-and-separate-live-preflight-approval",
        "repositoryVersionChanged": False,
        "livePreflightExecuted": False,
        "serverSideDryRunExecuted": False,
        "gitopsPinChangeAuthorized": False,
        "liveUpgradeAuthorized": False,
    }, "overall gate drift")
    require(value.get("nextCheckpoint") == "v0.12.4.1.5.1-external-secrets-live-preflight-evidence", "next checkpoint drift")


def set_path(value: dict[str, Any], path: tuple[Any, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.1.5-external-secrets-live-preflight.json"
    document_path = root / "docs/V0.12.4.1.5_EXTERNAL_SECRETS_LIVE_PREFLIGHT_CONTRACT.md"
    checker_path = root / "scripts/check-v0.12.4.1.5-external-secrets-live-preflight-contract.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5-external-secrets-live-preflight.py"
    test_path = root / "scripts/test-v0.12.4.1.5-external-secrets-live-preflight.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5-external-secrets-live-preflight.sh"
    contract = load(contract_path)
    validate_contract(contract)

    mutations = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("boundPredecessors", "firstHopPlanSha256"), "0" * 64),
        (("target", "environment"), "aws-test"),
        (("target", "candidateChartVersion"), "2.10.0"),
        (("target", "candidateChartSha256"), "0" * 64),
        (("target", "candidateRenderSha256"), "0" * 64),
        (("target", "candidateRenderObjectCount"), 36),
        (("privateRequest", "maximumApprovalWindowSeconds"), 7200),
        (("privateRequest", "minimumRemainingApprovalSeconds"), 0),
        (("privateRequest", "requestMode"), "0644"),
        (("verifyPhase", "awsCommandsAllowed"), True),
        (("verifyPhase", "repositoryPinMustRemainTwoEight"), False),
        (("executePhase", "requiredConfirmationValue"), "run"),
        (("executePhase", "serverSideDryRunRunsExactlyOnce"), False),
        (("executePhase", "serverSideDryRunStderrMustBeEmpty"), False),
        (("executePhase", "preAndPostProtectedProjectionMustMatch"), False),
        (("executePhase", "automaticRetry"), True),
        (("liveAssertions", "operatorApplicationMustRemainTwoEightSyncedHealthyAndIdle"), False),
        (("liveAssertions", "externalSecretMustBeReadyAndReferenceAwsCurrent"), False),
        (("secretBoundary", "awsGetSecretValueAllowed"), True),
        (("secretBoundary", "kubernetesSecretGetAllowed"), True),
        (("secretBoundary", "secretValueDigestAllowed"), True),
        (("forbiddenOperations",), []),
        (("resultBoundary", "preflightSuccessAuthorizesGitPinMutation"), True),
        (("resultBoundary", "failureMayBeRetriedWithoutNewRequest"), True),
        (("executionBoundary", "kubernetesPersistentMutationAuthorized"), True),
        (("executionBoundary", "gitVersionMutationAuthorized"), True),
        (("executionBoundary", "argocdOperationAuthorized"), True),
        (("overallGate", "liveUpgradeAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.1.6"),
    )
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, LivePreflightContractError):
            continue
        raise LivePreflightContractError(f"fail-open mutation {index}")

    predecessors = contract["boundPredecessors"]
    for path_key, digest_key in (
        ("artifactRenderProofPath", "artifactRenderProofSha256"),
        ("firstHopPlanPath", "firstHopPlanSha256"),
    ):
        path = root / predecessors[path_key]
        require(path.is_file() and file_sha256(path) == predecessors[digest_key], f"predecessor source drift: {path_key}")

    application = (root / "clusters/aws/base/platform/external-secrets.yaml").read_text()
    require("targetRevision: 2.8.0" in application, "repository pin changed")
    require("targetRevision: 2.9.0" not in application, "candidate pin applied early")

    executor = executor_path.read_text()
    for required in (
        "EXPECTED_SOURCE_SHA256S = (",
        "EXPECTED_SOURCE_PATHS = (",
        "EXPECTED_SOURCE_DIGESTS = tuple(zip(EXPECTED_SOURCE_PATHS, EXPECTED_SOURCE_SHA256S, strict=True))",
        "for relative, expected in EXPECTED_SOURCE_DIGESTS:",
        '"kubectl", "apply", "--server-side", "--dry-run=server"',
        '"--field-manager=v0.12.4.1.5-external-secrets-preflight"',
        '"-o", "name", "-f", str(context["render"])',
        '"aws", "sts", "get-caller-identity"',
        '"aws", "eks", "describe-cluster"',
        '"kubectl", "get", "--raw=/readyz"',
        '"operational_commands_executed": []',
        '"secret_value_read_executed": False',
        '"persistent_kubernetes_mutation_executed": False',
    ):
        require(required in executor, f"executor control missing: {required}")
    for forbidden in (
        "EXPECTED_SOURCE_DIGESTS = {",
        "EXPECTED_SOURCE_DIGESTS.items()",
        "get-secret-value", "update-secret", "put-secret", "kubectl diff",
        "force-unlock", "update-kubeconfig", "argocd app", "helm upgrade",
        "helm install", "kubectl annotate", "kubectl patch", "kubectl delete",
    ):
        require(forbidden not in executor, f"forbidden executor operation present: {forbidden}")
    digest_block = executor.split("EXPECTED_SOURCE_SHA256S = (", 1)[1].split("EXPECTED_SOURCE_PATHS = (", 1)[0]
    path_block = executor.split("EXPECTED_SOURCE_PATHS = (", 1)[1].split("EXPECTED_SOURCE_DIGESTS =", 1)[0]
    require(len(re.findall(r'"[0-9a-f]{64}"', digest_block)) == 6, "source digest separation drift")
    require(not re.search(r'"[0-9a-f]{64}"', path_block), "high-entropy digest returned to source path block")
    require(executor.count('"--dry-run=server"') == 1, "executor dry-run cardinality drift")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "It does not upgrade the operator",
        "executes no AWS, Kubernetes or Helm command",
        "Successful preflight evidence does not authorize changing the GitOps pin",
        "never calls AWS `GetSecretValue`",
        "does not run `aws eks update-kubeconfig`",
        "Preserve the private output directory and do not retry with the same request",
        "v0.12.4.1.5.1-external-secrets-live-preflight-evidence",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    require("v0.12.4.1.5-external-secrets-live-preflight-contract" in (root / "README.md").read_text(), "README checkpoint missing")
    require("v0.12.4.1.5 - External Secrets live preflight contract" in (root / "docs/ROADMAP.md").read_text(), "roadmap increment missing")
    require("## v0.12.4.1.5" in (root / "CHANGELOG.md").read_text(), "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "live-preflight source tracking drift")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable source mode drift: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable source mode drift: {path.name}")
        require_executable_worktree_mode(path.stat().st_mode, path.name)
    for accepted_mode in (0o755, 0o775):
        require_executable_worktree_mode(stat.S_IFREG | accepted_mode, "fixture")
    for rejected_mode in (0o644, 0o664):
        try:
            require_executable_worktree_mode(stat.S_IFREG | rejected_mode, "fixture")
        except LivePreflightContractError:
            continue
        raise LivePreflightContractError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1.5 External Secrets live-preflight contract and {len(mutations)} "
        "fail-closed mutations passed offline; chart 2.8.0 remains pinned."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
