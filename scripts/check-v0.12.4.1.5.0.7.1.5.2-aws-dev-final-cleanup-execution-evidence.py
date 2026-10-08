#!/usr/bin/env python3
"""Offline repository checker for final AWS-dev cleanup evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.5.2-aws-dev-final-cleanup-execution-evidence"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_contract(contract: dict) -> None:
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.5.2", "version changed")
    require(contract["status"] == "aws-dev-final-cleanup-execution-recorded", "status changed")
    require(contract["implementationBaselineCommit"] == "691b3d4ba3b5dfa387c7001b71f4571a84b9ff3e", "baseline changed")
    require(contract["completedAtUtc"] == "2026-10-08T09:59:49Z", "completion time changed")

    bindings = contract["artifactBindings"]
    expected_bindings = {
        "privateIncidentPrepareRequestSha256": "15e178bf565b80c50e441829955291bedcf430035c01b8e94d843731e729b625",
        "privateRecoveryRequestSha256": "25be3670ea1a75f6503827bfd53a0e643ea8d3056d3a83e6c2e7b269e324303c",
        "privateFinalRequestSha256": "45daf9637dd58acf77dc2126f66fc82ae3b7b96bfa86643b1233a2d275a17f65",
        "deleteSecurityGroupStdoutSha256": "fe1cb2564af4e2ea11993e6a2608d1bbcda6c1006bf5d4a15fb9809a25fe03f3",
        "targetSecurityGroupIdSha256": "e8a820dca7c3ab7408210f6779341938441519de137870e67278175c10f4d637",
        "recoveryResultSha256": "d555b99158ef0a05f6a4ba2cd4948b88d9583d902bc7dae6687f59973eacfffa",
        "binaryPlanSha256": "0e5cb1cfc9d780fbcff7e66c3fc91eefc3e70484e6817860cc3f7774c5f6c591",
        "planJsonSha256": "514994647727b84480fe90ac84233de85de83970d5b93188f160d6b65bbf3dac",
        "planTextSha256": "eca5c43b66cec89770a7c340a1f3cdbf5f17534b113ca1b2c1320b910b4fd820",
        "addressInventorySha256": "0ac013163aecf46232dbaeae9758e91e648f9f66cb2f662c040ff8e8ec432a99",
        "planRecordSha256": "353514cca8cea8bd44afaa4a77080d7952c4aa34b88eaf6edb03a3f16b6a8978",
        "applyStdoutSha256": "cbfaba955e3636196ef57241d78a6c82226fa30f63b77a40c3d1324dbb9bdb2d",
        "applyStderrSha256": EMPTY_SHA256,
        "finalStateSha256": "4e3668eaf7debd9cb732cd4339b86284af13f361d38f4536865ae9457c6b4d43",
        "finalCleanupEvidenceSha256": "680d1c418365756f4d74ed1fd3a85ab66cf6d9557d1fce2b34aff1491d7bf233",
        "finalCleanupResultSha256": "0b1a48b038014f1cdb215bfef504bf23d1f58bbcb97bdb6491e7cb7de67ea04a",
        "finalStateListSha256": EMPTY_SHA256,
        "securityGroupAbsenceStderrSha256": "c1d017e97d8c4f8499e8253738a3add76ec77e547b35922618f7234251a454f6",
        "vpcAbsenceStderrSha256": "f66d94619ab352cbf2214426f4027b7602f853e3b1ee2cf41dcebaf037f6150d",
        "s3HistoryBeforeSha256": "590ea77bae7e881fe7ead049548c91391ecd28e161ba62ef84b0a5d6077a7df6",
        "s3HistoryAfterSha256": "833acce4e6f3b2d1c611da07572cbc5d91081c3c161e3a6eaa62055a453016d9",
    }
    require(bindings == expected_bindings, "artifact bindings changed")

    plan = contract["reviewedPlan"]
    require(plan["humanReviewPassed"] is True, "human review changed")
    require(plan["complete"] is True and plan["errored"] is False and plan["applyable"] is True, "plan validity changed")
    require((plan["managedDeleteCount"], plan["dataChangeCount"], plan["resourceDriftCount"], plan["importCount"]) == (1, 0, 0, 0), "plan counts changed")
    require(plan["exactManagedAddresses"] == ["module.vpc.aws_vpc.this"], "plan address changed")
    require(plan["exactManagedActions"] == ["delete"], "plan action changed")

    recovery = contract["incidentAndRecovery"]
    for key in ("deleteReturnVerified", "deleteResponseGroupIdBound", "originalRunStoppedBeforeAbsenceProof", "orphanSecurityGroupAbsenceVerified"):
        require(recovery[key] is True, f"recovery fact changed: {key}")
    require(recovery["securityGroupDeleteRetried"] is False, "security-group retry changed")

    outcome = contract["validatedOutcome"]
    require(outcome["exactSavedPlanApplied"] is True, "exact-plan result changed")
    require(outcome["normalizedDestroyStarted"] == ["module.vpc.aws_vpc.this"], "destroy-start evidence changed")
    require(outcome["normalizedDestroyCompleted"] == ["module.vpc.aws_vpc.this"], "destroy-complete evidence changed")
    require((outcome["applyAddCount"], outcome["applyChangeCount"], outcome["applyDestroyCount"]) == (0, 0, 1), "apply summary changed")
    require(outcome["managedDestroyedCount"] == 1, "destroy count changed")
    require((outcome["managedStateAddressCount"], outcome["dataStateAddressCount"], outcome["totalStateAddressCount"]) == (0, 0, 0), "final state changed")
    for key in ("finalStateListEmpty", "securityGroupAbsent", "vpcAbsent", "lockObjectAbsent"):
        require(outcome[key] is True, f"success boundary changed: {key}")
    require((outcome["stateObjectVersionDelta"], outcome["stateDeleteMarkerDelta"]) == (1, 0), "state history changed")
    require((outcome["lockObjectVersionDelta"], outcome["lockDeleteMarkerDelta"]) == (1, 1), "lock history changed")
    require((outcome["lockLatestVersionCount"], outcome["lockLatestDeleteMarkerCount"]) == (0, 1), "latest lock state changed")

    for section in ("negativeExecutionEvidence", "privacyBoundary", "packageProducer", "authority"):
        require(all(value is False for value in contract[section].values()), f"false-only boundary changed: {section}")
    integration = contract["auditIntegration"]
    require(integration["standaloneOnDemandValidation"] is True, "standalone audit boundary changed")
    for key in ("requiredCiCheck", "workflowBound", "rootCiOrchestratorBound"):
        require(integration[key] is False, f"CI separation changed: {key}")
    scope = contract["scopeBoundary"]
    require(scope["awsDevLiveWorkClosed"] is True, "AWS-dev closure changed")
    require(scope["residualCostAuditExecuted"] is False and scope["accountWideCostFreeClaimed"] is False, "cost-claim boundary changed")
    require(scope["nextCheckpoint"] == "offline-generalized-teardown-hardening-design", "next checkpoint changed")

    serialized = json.dumps(contract, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\b\d{12}\b", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b"):
        require(re.search(pattern, serialized, re.IGNORECASE) is None, f"private material found: {pattern}")


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.5.2_AWS_DEV_FINAL_CLEANUP_EXECUTION_EVIDENCE.md"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    validate_contract(contract)
    require(not executor_path.exists(), "execution-evidence checkpoint must not have an executor")

    document = " ".join(document_path.read_text().split())
    for phrase in ("has no executor", "do not run AWS, Terraform or Kubernetes commands", "does not claim that the entire AWS account is cost free", "grant no authority for further AWS-dev work", "standalone, on-demand audit entry point", "not wired to the root CI validator"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.5.2"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.5.2 - AWS dev final cleanup execution evidence"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    root_ci = (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh").read_text()
    require(PREFIX not in root_ci, "standalone audit validator is bound to root CI")
    workflows = root / ".github/workflows"
    if workflows.exists():
        for path in workflows.glob("*.y*ml"):
            require(PREFIX not in path.read_text(), f"standalone audit validator is workflow-bound: {path.name}")

    tracked_paths = [contract_path, document_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "execution-evidence source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "trackedFileCount": len(tracked_paths), "executorCount": 0, "awsDevLiveWorkClosed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Final cleanup evidence check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
