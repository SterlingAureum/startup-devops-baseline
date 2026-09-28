#!/usr/bin/env python3
"""Validate the offline v0.12.3 promotion/lifecycle convergence closure."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any


class ClosureError(ValueError):
    """Raised when a promotion or lifecycle boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosureError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.3.4-promotion-lifecycle-convergence-closure-v1", "schema drift")
    require(value.get("version") == "v0.12.3.4", "version drift")
    require(value.get("status") == "promotion-and-lifecycle-convergence-complete", "status drift")
    require(value.get("protectedMainBaselineCommit") == "14c972040ce22b4b8468d3f319d9ca750b073bfb", "baseline drift")
    require(value.get("releaseModel") == {
        "buildOnce": True,
        "sameDigestAcrossEnvironments": True,
        "orderedEnvironments": ["aws-dev", "aws-test", "aws-prod"],
        "testPromotionPrPreparedAutomatically": True,
        "prodPromotionPrPreparedAutomatically": True,
        "pullRequestReviewAndMergeHumanOwned": True,
        "productionEnvironmentApprovalRequired": True,
        "absentEnvironmentStatus": "waiting_environment",
    }, "release model drift")
    require(value.get("lifecycleBoundary") == {
        "applicationWorkflowOwnsTerraform": False,
        "automaticEnvironmentCreation": False,
        "automaticEnvironmentDestroy": False,
        "automaticProductionMerge": False,
        "automaticProductionRollback": False,
        "maximumConcurrentDisposableEksEnvironments": 1,
    }, "lifecycle boundary drift")
    evidence = value.get("evidence", {})
    require(evidence.get("promotionPullRequest") == 169, "promotion PR drift")
    require(evidence.get("promotionPullRequestMerged") is True, "promotion merge evidence drift")
    require(evidence.get("exactReleasePathRoutingGithubValidated") is True, "release-route evidence drift")
    require(evidence.get("awsProdLivePromotionExecuted") is False, "production execution overclaim")
    require(evidence.get("integratedThreeEnvironmentRehearsalExecuted") is False, "integrated rehearsal overclaim")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and boundary, "missing execution boundary")
    require(all(item is False for item in boundary.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4-upgrade-lifecycle", "next checkpoint drift")
    require(value.get("deferred") == {
        "finalIntegratedDevTestProdCommercialRehearsal": "v1.0-rc.3",
        "repositoryPhysicalRestructure": "v1.0",
        "repositoryWideHumanReview": "v1.0",
    }, "deferred scope drift")
    require(value.get("packageProducer") == {
        "runsAws": False,
        "runsTerraform": False,
        "runsKubernetes": False,
        "mutatesGithub": False,
    }, "package producer drift")


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.3.4-promotion-lifecycle-convergence-closure.json"
    document_path = root / "docs/V0.12.3.4_PROMOTION_LIFECYCLE_CONVERGENCE_CLOSURE.md"
    checker_path = root / "scripts/check-v0.12.3.4-promotion-lifecycle-closure.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutations: list[dict[str, Any]] = []
    for path, replacement in (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("releaseModel", "sameDigestAcrossEnvironments"), False),
        (("releaseModel", "pullRequestReviewAndMergeHumanOwned"), False),
        (("releaseModel", "productionEnvironmentApprovalRequired"), False),
        (("lifecycleBoundary", "applicationWorkflowOwnsTerraform"), True),
        (("lifecycleBoundary", "automaticEnvironmentCreation"), True),
        (("lifecycleBoundary", "maximumConcurrentDisposableEksEnvironments"), 2),
        (("evidence", "awsProdLivePromotionExecuted"), True),
        (("executionBoundary", "githubMutationAuthorized"), True),
        (("nextCheckpoint",), "v1.0"),
    ):
        candidate = deepcopy(contract)
        cursor = candidate
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = replacement
        mutations.append(candidate)
    for index, candidate in enumerate(mutations, 1):
        try:
            validate_contract(candidate)
        except (AttributeError, KeyError, TypeError, ClosureError):
            continue
        raise ClosureError(f"fail-open mutation {index}")

    foundation = load(root / "delivery/contracts/v0.12.0-production-readiness-foundation.json")
    expected_foundation = {
        "buildOnce": True, "sameDigestAcrossEnvironments": True,
        "orderedEnvironments": ["aws-dev", "aws-test", "aws-prod"],
        "testPromotionPrPreparedAutomatically": True,
        "prodPromotionPrPreparedAutomatically": True,
        "pullRequestMergeIsHuman": True,
        "prodEnvironmentApprovalRequired": True,
        "automaticEnvironmentCreation": False,
        "automaticEnvironmentDestroy": False,
        "automaticProductionMerge": False,
        "automaticProductionRollback": False,
        "absentEnvironmentStatus": "waiting_environment",
        "applicationLifecycleOwnsTerraform": False,
        "maximumConcurrentDisposableEksEnvironments": 1,
    }
    require(foundation.get("releaseAndLifecycle") == expected_foundation, "foundation release/lifecycle drift")

    orchestrator = (root / ".github/workflows/demo-api-release-orchestrator.yaml").read_text()
    promotion = (root / ".github/workflows/demo-api-promote-environment.yaml").read_text()
    derive = (root / "scripts/derive-demo-api-orchestration-plan.py").read_text()
    require("source_environment: aws-dev\n      target_environment: aws-test" in orchestrator, "test promotion edge drift")
    require("source_environment: aws-test\n      target_environment: aws-prod" in orchestrator, "prod promotion edge drift")
    require("DEMO_API_AWS_TEST_PROMOTION_ENABLED" in orchestrator, "test promotion opt-in missing")
    require("DEMO_API_AWS_PROD_PROMOTION_ENABLED" in orchestrator, "prod promotion opt-in missing")
    require("name: ${{ inputs.target_environment }}" in promotion, "target Environment missing")
    require("deployment: false" in promotion, "promotion Environment boundary drift")
    require("waiting_environment" in derive, "absent-environment state missing")
    combined = (orchestrator + promotion).lower()
    for forbidden in ("terraform init", "terraform plan", "terraform apply", "terraform destroy", "gh pr merge", "eksctl create", "eksctl delete"):
        require(forbidden not in combined, f"application lifecycle authority drift: {forbidden}")

    document = " ".join(document_path.read_text().split())
    for phrase in ("builds an application artifact once", "review and merge remain human owned", "waiting_environment", "does not prove a live aws-prod deployment", "v0.12.4"):
        require(phrase in document, f"closure document boundary missing: {phrase}")
    roadmap = (root / "docs/ROADMAP.md").read_text()
    start = roadmap.index("- v0.12.3 - release-promotion")
    end = roadmap.index("- v0.12.3.1 -", start)
    require("- completed" in roadmap[start:end], "roadmap v0.12.3 remains open")

    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", str(contract_path.relative_to(root)), str(document_path.relative_to(root)), str(checker_path.relative_to(root))],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "closure source tracking drift")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    require(modes[str(contract_path.relative_to(root))] == "100644", "contract mode drift")
    require(modes[str(document_path.relative_to(root))] == "100644", "document mode drift")
    require(modes[str(checker_path.relative_to(root))] == "100755", "checker mode drift")
    print(f"v0.12.3.4 promotion/lifecycle closure and {len(mutations)} fail-closed mutations passed offline.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
