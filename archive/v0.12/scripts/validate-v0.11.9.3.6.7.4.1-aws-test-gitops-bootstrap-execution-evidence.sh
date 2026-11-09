#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.4-guarded-aws-test-gitops-bootstrap.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.7.4.1"
assert contract["predecessor"] == "v0.11.9.3.6.7.4"
assert contract["status"] == "aws-test-gitops-bootstrap-execution-evidence-recorded"
assert contract["implementationBaselineCommit"] == "4aa621267676339546a26444a7fe235285872a74"
assert contract["nextCheckpoint"] == (
    "design-guarded-aws-test-root-application-deploy-with-fresh-preflight-and-separate-approval"
)

expected_inputs = {
    "bootstrapContract": (
        "delivery/contracts/v0.11.9.3.6.7.4-guarded-aws-test-gitops-bootstrap.json",
        "8c823b06cf3784bdb1229f84921979f0927c75a7a964397bc68630c00f5f4177",
    ),
    "bootstrapExecutor": (
        "scripts/execute-v0.11.9.3.6.7.4-aws-test-gitops-bootstrap.py",
        "59fa05e351552e560b40a18a27fdd3b84cd7ab780c06cb62a5b98a72b592a241",
    ),
    "bootstrapValidator": (
        "scripts/validate-v0.11.9.3.6.7.4-guarded-aws-test-gitops-bootstrap.sh",
        "586b2b4c625bfad2cfd162a2bbd3e9e3090d4a643dba9cae927e2334eebd8eb8",
    ),
    "sharedBootstrap": (
        "scripts/bootstrap-eks-argocd.sh",
        "e849aa6b6e9cf688c8425c8670cb67dba00e2c794b481c83c9f89570c1d2f37f",
    ),
    "applyAndResumeEvidence": (
        "delivery/contracts/v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence.json",
        "6ff2fef31b72a513289fcb1a20204545012ddd24fbdb37ccc5806789686ab56f",
    ),
}
assert set(contract["reviewedRepositoryInputs"]) == set(expected_inputs)
for key, (path, expected) in expected_inputs.items():
    assert contract["reviewedRepositoryInputs"][key] == {"path": path, "sha256": expected}
    assert digest(root / path) == expected, path

initial = contract["initialVerifyAttempt"]
assert initial == {
    "executorExit": 1,
    "resultSha256": EMPTY,
    "stderrSha256": "0296b157282a7b9c98cb2df702568da1127766a65b8008623ae5be376e15b6f1",
    "stderrBytes": 80,
    "failureStage": "kubeconfig-endpoint-match",
    "awsAccountVerifiedBeforeStop": True,
    "eksClusterActiveBeforeStop": True,
    "terraformStateAcceptedBeforeStop": True,
    "mutationExecuted": False,
    "automaticRetryPerformed": False,
}

kubeconfig = contract["isolatedKubeconfigPreparation"]
assert kubeconfig["awsCliDryRun"] is True
assert kubeconfig["defaultKubeconfigModified"] is False
assert kubeconfig["initialSha256"] == "9e8bdb782ccc8a368b7e64f64abe7bfa51307f0d9855cb1c4b505cd05968f9b2"
assert kubeconfig["initialStderrSha256"] == EMPTY
assert kubeconfig["initialStderrBytes"] == 0
assert kubeconfig["fileModeRestated"] == "0600"
assert kubeconfig["privatePathCommitted"] is False

verification = contract["successfulVerification"]
assert verification["executorExit"] == 0
assert verification["resultSha256"] == "e56d86d139d51c93c417de6d1891ff98cdbc4141219104f4ba922d51e2306bdc"
assert verification["stderrSha256"] == EMPTY
assert verification["stderrBytes"] == 0
assert verification["status"] == "aws-test-gitops-bootstrap-inputs-verified"
assert verification["controlPlaneCommit"] == "4aa621267676339546a26444a7fe235285872a74"
assert verification["appliedControlPlaneCommit"] == "1376129d42c6dbc19ffb57c97244d2b31ddd4ff7"
assert verification["remainingSessionSeconds"] == 9218
assert verification["stateAddressCount"] == 103
for key in ("eksClusterActive", "argocdNamespaceAbsent", "rootApplicationAbsent"):
    assert verification[key] is True, key
for key in ("gitopsBootstrapAuthorized", "terraformCommandExecuted", "kubernetesMutationExecuted"):
    assert verification[key] is False, key

approval = contract["executionApproval"]
assert datetime.fromisoformat(approval["notAfterUtc"].replace("Z", "+00:00")).isoformat() == "2026-09-12T17:38:53+00:00"
assert approval["oneExecutionApproved"] is True
assert approval["reviewedVerifySha256"] == verification["resultSha256"]
assert approval["reviewedStateSha256"] == "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b"
assert approval["reviewedKubeconfigSha256"] == kubeconfig["initialSha256"]
assert approval["sharedBootstrapInvocationCountApproved"] == 1
assert approval["argocdVersionApproved"] == "v3.5.2"
assert approval["irsaServiceAccountsApproved"] == 2
for key in ("argocdNamespaceAndInstallApproved", "awsLoadBalancerControllerApplicationApproved", "privateOutputCaptureApproved"):
    assert approval[key] is True, key
for key in (
    "terraformMutationApproved", "rootApplicationApproved",
    "otherAwsOrKubernetesMutationApproved", "secretValueReadApproved",
    "automaticRetryApproved", "automaticRepairApproved", "trafficApproved",
    "qualificationApproved", "promotionApproved", "teardownApproved",
):
    assert approval[key] is False, key

execution = contract["execution"]
assert execution["executorExit"] == 0
assert execution["resultSha256"] == "ad674765975674e1f5aa0abad2cb6bbccd17b5c78cf868b8cffe4a098d4bf80a"
assert execution["resultBytes"] == 1003
assert execution["stderrSha256"] == EMPTY
assert execution["stderrBytes"] == 0
assert execution["status"] == "aws-test-gitops-bootstrap-complete"
assert execution["controlPlaneCommit"] == verification["controlPlaneCommit"]
assert execution["appliedControlPlaneCommit"] == verification["appliedControlPlaneCommit"]
assert execution["argocdVersion"] == "v3.5.2"
assert execution["gitopsBootstrapExecuted"] is True
for key in (
    "rootApplicationDeployed", "terraformPlanExecuted", "terraformApplyExecuted",
    "terraformDestroyExecuted", "automaticRetryPerformed", "trafficGenerated",
    "qualificationExecuted", "privateResourceIdentityEmitted",
):
    assert execution[key] is False, key

state = contract["stateAndKubeconfig"]
assert state["terraformState"]["beforeSha256"] == state["terraformState"]["afterSha256"] == approval["reviewedStateSha256"]
assert state["terraformState"]["unchanged"] is True
assert state["terraformState"]["committed"] is False
assert state["isolatedKubeconfig"]["beforeSha256"] == approval["reviewedKubeconfigSha256"]
assert state["isolatedKubeconfig"]["afterSha256"] == "b1f390903139c1d49a76bf5afcfdad892c2c6a7828310a3ecf791efd6808cd0f"
assert state["isolatedKubeconfig"]["changedOnlyByApprovedBootstrap"] is True
assert state["isolatedKubeconfig"]["committed"] is False

artifacts = contract["privateArtifactInventory"]
assert artifacts["directoryModeRestated"] == "0700"
assert artifacts["fileModeRestated"] == "0600"
assert artifacts["fileCount"] == 62
assert artifacts["totalBytes"] == 174294
assert artifacts["stdoutFileCount"] == artifacts["stderrFileCount"] == 31
assert artifacts["emptyFileCount"] == 30
assert artifacts["nonemptyFileCount"] == 32
assert artifacts["bootstrapStdout"] == {
    "sha256": "e1004e6cea91de51abb370a37c398ce91e584ad408c8257b6989de995c0c9142",
    "bytes": 4969,
}
assert artifacts["bootstrapStderr"] == {
    "sha256": "f9d72d2ce3318e9381de39d14d85fba0e3ce452ce9b68d721a51e4d21242dc78",
    "bytes": 193,
    "lineCount": 1,
    "warningLineCount": 1,
    "otherLineCount": 0,
    "failureMarkerFound": False,
    "humanReviewedAsNonFatal": True,
}
assert artifacts["stableReadOnlyOutputs"] == {
    "callerIdentitySha256": "66010a9aa506310c53e81087b9b6228cd6632dc72a8afe96d5556b56c64f6d27",
    "clusterInventorySha256": "9e95155afd2fcca6cd7eebc4158020b8b32800ac42948a6237f9b80949615ef9",
    "clusterDescriptionSha256": "f1de181f9e03d379a819468ea6b3f5df3774cf0a32f26eff8cae66980515888f",
    "metadataObservationSha256": "b56815ad21d9c784844929c040d9ec27a83ad016bdfff7405798801b5ae3a1ac",
    "terraformStateListSha256": "9c0c0fbce81f313a12d088bb0d071cfa20f911c1abb69fb35841de8dea7cdd96",
    "kubernetesReadyzSha256": "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df",
    "albRoleOutputSha256": "4af8a2de9f2adfb166517d77914ddb16aa4c2ee79bc87f0680f148f5cf2a3903",
    "karpenterRoleOutputSha256": "5bc9c8117d5439152376eb5bcfb09e025d5378c5f9ebbe07dae3d7caae5231da",
    "matchedBeforeAndAfter": True,
}
assert set(artifacts["postBootstrapOutputs"]) == {
    "argocdNamespaceSha256", "argocdServerSha256", "argocdRepoServerSha256",
    "argocdApplicationControllerSha256", "albServiceAccountSha256",
    "karpenterServiceAccountSha256", "awsLoadBalancerControllerApplicationSha256",
    "rootApplicationAbsenceStderrSha256",
}
assert artifacts["rawContentCommitted"] is False
assert artifacts["privatePathCommitted"] is False

assert contract["finalRepositoryState"] == {
    "head": "4aa621267676339546a26444a7fe235285872a74",
    "originMain": "4aa621267676339546a26444a7fe235285872a74",
    "worktreeClean": True,
    "protectedMainChecksPassed": True,
}
assert not any(contract["privacyBoundary"].values())
boundary = contract["operationBoundary"]
for key in (
    "gitopsBootstrapExecutedOnce", "argocdInstalled",
    "irsaServiceAccountsConfigured", "awsLoadBalancerControllerApplicationApplied",
):
    assert boundary[key] is True, key
for key in set(boundary) - {
    "gitopsBootstrapExecutedOnce", "argocdInstalled",
    "irsaServiceAccountsConfigured", "awsLoadBalancerControllerApplicationApplied",
}:
    assert boundary[key] is False, key
assert not any(contract["packageProducer"].values())
PY

"${PREDECESSOR}"

echo "v0.11.9.3.6.7.4.1 aws-test GitOps bootstrap execution evidence passed; no live operation was executed."
