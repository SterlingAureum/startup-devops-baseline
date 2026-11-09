#!/usr/bin/env python3
"""Validate the final v0.12 scope, evidence, deferrals, and handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.13-v0.12-scope-and-evidence-closure"
BASELINE = "e9e5abe4c993d8835b2f3b39125632eb3f29039d"
MANIFEST_SHA256 = "f0985edb929a6a135943f39d703fc38d658c7a783812348e01703a5a19a5a58b"
FORBIDDEN_CLAIMS = [
    "v0.12-proves-full-commercial-production-readiness",
    "aws-test-fresh-integrated-live-lifecycle-passed",
    "aws-prod-live-acceptance-passed",
    "external-secrets-live-upgrade-passed",
    "shared-dev-test-teardown-has-live-command-adapters",
    "application-teardown-removes-remote-state-backend",
    "aws-account-wide-zero-cost-guaranteed",
    "repository-wide-human-review-complete",
]
SOURCE_EVIDENCE = [
    {
        "role": "production-readiness-scope-and-guardrails",
        "path": "delivery/contracts/v0.12.0-production-readiness-foundation.json",
        "sha256": "271de6daff8009a4266e1a4f199fc1f33085ced03336548faae45f095fc02881",
    },
    {
        "role": "remote-state-bootstrap-live-validation",
        "path": "delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json",
        "sha256": "e4e1cdb74b473c3588733ddd4f01b37291d2ec9705d90a5bf7d35818c2f4ffae",
    },
    {
        "role": "nonempty-state-migration-terminal-recovery",
        "path": "delivery/contracts/v0.12.2.3.1.0.2.0.1.2.0.1.2-terminal-recovery-evidence.json",
        "sha256": "be9ed6753db05e82406b5d71c83623246632e7516c4978479f0170c67b1d0034",
    },
    {
        "role": "ci-feedback-efficiency-closure",
        "path": "delivery/contracts/v0.12.3.3-ci-feedback-efficiency-closure.json",
        "sha256": "39f5a30e4c0c0a2fd7e543e87785e1aeaaa8f82ce3a34b639149222963982a36",
    },
    {
        "role": "promotion-lifecycle-convergence",
        "path": "delivery/contracts/v0.12.3.4-promotion-lifecycle-convergence-closure.json",
        "sha256": "a0a1e92b539a7cb0d93c931782686c69dfa90c23c21dff3e618c3c81215821ec",
    },
    {
        "role": "platform-upgrade-live-preflight-boundary",
        "path": "delivery/contracts/v0.12.4.1.5-external-secrets-live-preflight.json",
        "sha256": "db6e968edaa77660a1be61c1aea0dcf49a4293d07080eb01ca47142c40ef166f",
    },
    {
        "role": "aws-dev-final-cleanup-execution-evidence",
        "path": "delivery/contracts/v0.12.4.1.5.0.7.1.5.2-aws-dev-final-cleanup-execution-evidence.json",
        "sha256": "9d50a498cc2ad6525b8a15b8ccaacd2a3de250dc4cf64949e38ff397618906a1",
    },
    {
        "role": "shared-dev-test-offline-teardown-closure",
        "path": "delivery/contracts/v0.12.4.1.5.0.7.1.6.12-shared-dev-test-offline-closure.json",
        "sha256": "1ab8f2b66254d4881b40dfbc0ab02a32709fb40fd87c667ba3cac54e374bdf5c",
    },
]


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def by_environment(manifest: dict) -> dict:
    rows = manifest["environmentEvidence"]
    require([row["environment"] for row in rows] == ["aws-dev", "aws-test", "aws-prod"], "environment evidence order changed")
    return {row["environment"]: row for row in rows}


def validate_contract(contract: dict, fixture: dict) -> None:
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.13", "version changed")
    require(contract["status"] == "v0.12-scope-and-evidence-closed-with-explicit-deferrals", "status changed")
    require(contract["repository"] == "SterlingAureum/startup-devops-baseline", "repository changed")
    require(contract["implementationBaselineCommit"] == BASELINE, "baseline changed")
    require(contract["predecessor"] == "delivery/contracts/v0.12.4.1.5.0.7.1.6.12-shared-dev-test-offline-closure.json", "predecessor changed")
    require(contract["manifestPath"] == "delivery/contracts/v0.12-final-evidence-manifest.json", "manifest path changed")
    require(contract["manifestSha256"] == MANIFEST_SHA256, "manifest binding changed")
    assertions = contract["closureAssertions"]
    expected_true = {
        "v012AcceptedScopeClosed", "remoteStateBootstrapLiveValidated",
        "nonemptyStateMigrationRehearsalComplete", "remoteS3StateOperationalSourceOfTruth",
        "ciFeedbackEfficiencyClosed", "promotionLifecycleConverged",
        "awsDevCreateQualificationAndTeardownComplete", "sharedDevTestOfflineTeardownClosed",
        "postV012ReviewHandoffRecorded",
    }
    expected_false = {
        "externalSecretsLiveUpgradeExecuted", "freshAwsTestIntegratedLifecycleExecuted",
        "awsProdLiveQualified", "sharedLiveTeardownAdaptersImplemented",
        "remoteStateBackendRetired", "repositoryWideHumanReviewComplete",
        "productionReadinessClaimed",
    }
    require(set(assertions) == expected_true | expected_false, "closure assertion inventory changed")
    require(all(assertions[key] is True for key in expected_true), "completed scope assertion changed")
    require(all(assertions[key] is False for key in expected_false), "deferred scope overclaimed")
    require(contract["roadmapLifecycle"] == {
        "priorStatusAccepted": "In Progress",
        "closedStatus": fixture["expectedRoadmapStatus"],
        "closedStatusRequiresFinalManifest": True,
        "legacyInProgressStillValidatorCompatible": True,
    }, "roadmap lifecycle changed")
    validation = contract["validationContract"]
    require(validation["sourceEvidenceDigestCount"] == fixture["expectedSourceEvidenceCount"] == 8, "source evidence count changed")
    for key in ("crossWorkstreamFactChecksRequired", "negativeOverclaimMutationTestsRequired", "privacyScanRequired", "rootStructureValidationRequired"):
        require(validation[key] is True, f"closure validation disabled: {key}")
    for key in ("cloudAccessRequired", "kubernetesAccessRequired", "terraformExecutionRequired", "githubMutationRequired"):
        require(validation[key] is False, f"closure gained execution requirement: {key}")
    require(all(value is False for value in contract["packageProducer"].values()), "package producer gained live capability")
    require(contract["next"] == "Begin the post-v0.12 repository and architecture review before any additional live expansion.", "handoff changed")


def validate_manifest(manifest: dict, fixture: dict) -> None:
    require(manifest["schemaVersion"] == "v0.12-final-evidence-manifest-v1", "manifest schema changed")
    require(manifest["version"] == "v0.12", "manifest version changed")
    require(manifest["closureCheckpoint"] == "v0.12.4.1.5.0.7.1.6.13", "closure checkpoint changed")
    require(manifest["implementationBaselineCommit"] == BASELINE, "manifest baseline changed")
    require(manifest["status"] == "completed-with-explicit-live-and-review-deferrals", "manifest status changed")
    require(len(SOURCE_EVIDENCE) == fixture["expectedSourceEvidenceCount"] == 8, "source evidence fixture changed")
    require(manifest["sourceEvidence"] == SOURCE_EVIDENCE, "source evidence inventory changed")
    environments = by_environment(manifest)
    require(list(environments) == fixture["expectedEnvironmentOrder"], "environment fixture changed")
    require(environments["aws-dev"] == {
        "environment": "aws-dev",
        "acceptance": "live-clean-room-create-qualification-and-teardown-complete",
        "currentApplicationState": "destroyed",
        "residualCostAuditExecuted": False,
        "accountWideZeroCostClaimed": False,
    }, "aws-dev closure facts changed")
    require(environments["aws-test"]["freshIntegratedLiveLifecycleExecutedInV012"] is False, "aws-test live lifecycle overclaimed")
    require(environments["aws-test"]["productionEquivalentClaimed"] is False, "aws-test production equivalence overclaimed")
    require(environments["aws-prod"]["acceptance"] == "not-live-qualified", "aws-prod qualification overclaimed")
    require(environments["aws-prod"]["livePromotionExecuted"] is False and environments["aws-prod"]["liveLifecycleExecuted"] is False, "aws-prod live execution overclaimed")
    require(manifest["stateBackend"] == {
        "remoteS3StateIsOperationalSourceOfTruth": True,
        "applicationTeardownIncludesBackend": False,
        "backendRetired": fixture["expectedRemoteStateBackendRetired"],
        "retirementRequiresSeparateRetentionPlanReviewAndApproval": True,
        "zeroOngoingBackendCostClaimed": False,
    }, "state backend closure boundary changed")
    require(manifest["forbiddenClaims"] == FORBIDDEN_CLAIMS, "forbidden claims changed")
    require(len(FORBIDDEN_CLAIMS) == fixture["expectedForbiddenClaimCount"], "forbidden claim fixture changed")
    require(len(manifest["deferredWork"]) == fixture["expectedDeferredWorkCount"] == 10, "deferred work inventory changed")
    require(manifest["privacyBoundary"] == {
        "rawPrivateEvidenceCommitted": False,
        "awsAccountIdentifiersCommitted": False,
        "resourceIdentifiersCommitted": False,
        "stateOrPlanBytesCommitted": False,
        "privatePathsCommitted": False,
        "redactedRepositoryRecordsOnly": True,
    }, "privacy boundary changed")
    require(manifest["newLiveExecutionAuthorized"] == fixture["expectedLiveExecutionAuthorization"] is False, "live authority added")
    require(manifest["productionReadinessClaimed"] == fixture["expectedProductionReadinessClaim"] is False, "production readiness overclaimed")


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    manifest_path = root / "delivery/contracts/v0.12-final-evidence-manifest.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.13_V0.12_SCOPE_AND_EVIDENCE_CLOSURE.md"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    contract = json.loads(contract_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    fixture = json.loads(fixture_path.read_text())
    validate_contract(contract, fixture)
    validate_manifest(manifest, fixture)
    require(digest(manifest_path) == contract["manifestSha256"] == MANIFEST_SHA256, "final manifest digest changed")

    sources = {}
    for row in manifest["sourceEvidence"]:
        path = root / row["path"]
        require(path.is_file() and not path.is_symlink(), f"source evidence missing or linked: {row['path']}")
        require(digest(path) == row["sha256"], f"source evidence digest changed: {row['path']}")
        sources[row["role"]] = json.loads(path.read_text())
    require(sources["production-readiness-scope-and-guardrails"]["status"] == "delivered-offline-design-only", "foundation fact changed")
    bootstrap = sources["remote-state-bootstrap-live-validation"]
    require(bootstrap["validatedOutcome"]["backendFoundationCreated"] is True, "state bootstrap fact changed")
    require(bootstrap["validatedOutcome"]["bootstrapStateRemainsLocalAndPrivate"] is True, "bootstrap state fact changed")
    migration = sources["nonempty-state-migration-terminal-recovery"]
    require(migration["closureDecision"]["stateMigrationRehearsalComplete"] is True, "state migration closure changed")
    require(migration["closureDecision"]["remoteS3StateIsOperationalSourceOfTruth"] is True, "remote state authority changed")
    ci = sources["ci-feedback-efficiency-closure"]
    require(ci["convergence"]["stableRequiredQualityGatePreserved"] is True, "CI required check changed")
    require(ci["convergence"]["historicalRuntimeReplayExecuted"] is False, "historical replay re-enabled")
    promotion = sources["promotion-lifecycle-convergence"]
    require(promotion["releaseModel"]["orderedEnvironments"] == ["aws-dev", "aws-test", "aws-prod"], "promotion order changed")
    require(promotion["evidence"]["awsProdLivePromotionExecuted"] is False, "prod promotion overclaimed")
    require(promotion["evidence"]["integratedThreeEnvironmentRehearsalExecuted"] is False, "integrated rehearsal overclaimed")
    upgrade = sources["platform-upgrade-live-preflight-boundary"]
    require(upgrade["status"] == "external-secrets-2.9.0-live-preflight-contract-ready-offline", "upgrade boundary changed")
    require(upgrade["executionBoundary"]["kubernetesPersistentMutationAuthorized"] is False, "upgrade mutation authority changed")
    cleanup = sources["aws-dev-final-cleanup-execution-evidence"]
    require(cleanup["validatedOutcome"]["totalStateAddressCount"] == 0, "aws-dev final state changed")
    require(cleanup["validatedOutcome"]["vpcAbsent"] is True, "aws-dev VPC closure changed")
    require(cleanup["scopeBoundary"]["residualCostAuditExecuted"] is False, "residual audit overclaimed")
    offline = sources["shared-dev-test-offline-teardown-closure"]
    require(offline["offlineProof"]["freshProcessCount"] == 16 and offline["offlineProof"]["fixedFakeBackendCallCount"] == 98, "offline teardown proof changed")
    require(all(gap["blocksLiveExecutionClaim"] is True for gap in offline["liveReadinessGaps"]), "live teardown gap relaxed")

    roadmap = (root / "docs/ROADMAP.md").read_text()
    start = roadmap.index("## v0.12 - Production Readiness Capstone")
    end = roadmap.index("## v1.0 - Production-ready Commercial Baseline", start)
    section = roadmap[start:end]
    require(f"Status: {fixture['expectedRoadmapStatus']}" in section, "v0.12 roadmap status changed")
    require("v0.12.4.1.5.0.7.1.6.13 - v0.12 scope and evidence closure" in section, "v0.12 closure roadmap entry missing")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("complete within its accepted scope", "not a claim", "eight redacted repository evidence roots", "remote-state backend remains active", "post-v0.12 repository and architecture review"):
        require(phrase in document, f"closure document boundary missing: {phrase}")
    serialized = json.dumps({"contract": contract, "manifest": manifest, "fixture": fixture}, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized, re.IGNORECASE) is None, f"closure record contains private identity marker: {pattern}")
    for forbidden in (root / f"scripts/exercise-{PREFIX}.py", root / f"scripts/execute-{PREFIX}.py"):
        require(not forbidden.exists(), f"closure checkpoint gained runtime entrypoint: {forbidden.name}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.13"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
        (root / "scripts/validate-v0.12.0-production-readiness-foundation.sh", "Completed with explicit live and review deferrals"),
    ):
        require(marker in path.read_text(), f"repository closure marker missing: {marker}")

    tracked_paths = [contract_path, manifest_path, fixture_path, document_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "closure source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, manifest_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "sourceEvidenceCount": len(manifest["sourceEvidence"]),
        "forbiddenClaimCount": len(manifest["forbiddenClaims"]),
        "deferredWorkCount": len(manifest["deferredWork"]),
        "v012ScopeClosed": True,
        "productionReadinessClaimed": False,
        "newLiveExecutionAuthorized": False,
        "trackedFileCount": len(tracked_paths),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"v0.12 scope closure check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
