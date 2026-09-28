#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-full}"
if [[ "${mode}" != "full" && "${mode}" != "--structure-only" ]]; then
  echo "Usage: $0 [--structure-only]" >&2
  exit 2
fi

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PYTHON'
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.3.3-ci-feedback-efficiency-closure.json"
document_path = root / "docs/V0.12.3.3_CI_FEEDBACK_EFFICIENCY_CLOSURE.md"
validator_path = root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh"


class ClosureError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ClosureError(message)


def load(path):
    require(path.is_file(), f"missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path.relative_to(root)}")
    return value


def validate(value, *, check_repository=True):
    require(value.get("schemaVersion") == "v0.12.3.3-ci-feedback-efficiency-closure-v1", "schema drift")
    require(value.get("version") == "v0.12.3.3", "version drift")
    require(value.get("status") == "delivered-offline-after-protected-main-integration", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "c872bc9ab8f1237aa432430a4e7a7d2cb63a4756", "main baseline drift")

    measurement = value.get("measurements")
    require(measurement == {
        "preRoutingFullGateElapsedSeconds": 302,
        "convergedFullGateReportedElapsedSeconds": 29,
        "convergedFullGateWallSeconds": 29.486,
        "convergedFullGateUserSeconds": 13.783,
        "convergedFullGateSystemSeconds": 13.263,
        "convergedValidationLogSha256": "3352a9b113eda2c73cd50bfb505887753f49787017cbcdc01ece75a39c9aabed",
        "environmentSpecificBenchmark": True,
        "performanceSlaClaimed": False,
    }, "measurement drift")

    convergence = value.get("convergence")
    for key in (
        "stableRequiredQualityGatePreserved",
        "documentationFastRoutePreserved",
        "exactReleaseRoutePreserved",
        "coreAndAmbiguousChangesRemainFull",
        "imagePublishDuplicateFullReplayRemoved",
        "staticGitAttestationRequired",
        "currentV012StructureValidationRequired",
    ):
        require(convergence.get(key) is True, f"convergence control disabled: {key}")
    require(convergence.get("historicalEntrypointCount") == 112, "historical entrypoint count drift")
    require(convergence.get("historicalRuntimeReplayExecuted") is False, "historical runtime replay enabled")
    require(convergence.get("detachedHistoricalWorktreeCreated") is False, "detached worktree enabled")

    evidence = value.get("evidenceBoundary")
    require(evidence == {
        "localFullGatePassed": True,
        "protectedMainContainsStaticAttestationConvergence": True,
        "postMergeGithubRunRecordedInRepository": False,
        "futureTimingIsEnvironmentDependent": True,
    }, "evidence boundary drift")

    recovery = value.get("terraformRecoveryBoundary")
    require(recovery == {
        "stateExercisePausedDuringCiRepair": True,
        "reviewedRefreshOnlyApplyAlreadyExecuted": True,
        "expectedPersistedStateSerial": 2,
        "refreshOnlyApplyMayBeRetried": False,
        "nextAllowedDesign": "read-only-post-apply-state-recovery",
        "stateRecoveryResumedByThisIncrement": False,
    }, "Terraform recovery boundary drift")

    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and boundary, "missing execution boundary")
    require(all(enabled is False for enabled in boundary.values()), "live authority enabled")
    require(value.get("deferred") == {
        "exactMergeTreeAttestedCoreGateReuse": "v1.0",
        "historicalValidatorArchival": "v1.0",
        "repositoryPhysicalRestructure": "v1.0",
        "repositoryWideHumanReview": "v1.0",
    }, "deferred boundary drift")

    if not check_repository:
        return

    predecessor = load(root / "delivery/contracts/v0.12.3.2-post-promotion-historical-snapshot.json")
    require(predecessor["historicalSnapshot"]["entrypointCount"] == 112, "predecessor entrypoint drift")
    require(predecessor["historicalSnapshot"]["detachedWorktreeCreated"] is False, "predecessor detached worktree drift")
    require(predecessor["historicalSnapshot"]["runtimeReplayRequired"] is False, "predecessor runtime replay drift")

    routing = load(root / "delivery/contracts/v0.12.3.1-ci-change-impact-routing.json")
    require(routing["observedFullGate"]["totalElapsedSeconds"] == 302, "pre-routing measurement drift")
    require(routing["routing"]["unknownOrAmbiguousChangeMode"] == "full", "routing fallback drift")

    document = document_path.read_text()
    document_words = " ".join(document.split())
    for phrase in (
        "completed in 29",
        "environment-specific observation, not a performance SLA",
        "does not create a detached worktree",
        "does not replay a v0.11 validator",
        "must not be applied again",
        "separately approved read-only post-apply recovery",
    ):
        require(phrase in document_words, f"closure boundary missing: {phrase}")

    readme = (root / "README.md").read_text()
    require("v0.12.3.3-ci-feedback-efficiency-closure" in readme, "README checkpoint missing")
    require("without runtime replay" in readme, "README static attestation missing")

    changelog = (root / "CHANGELOG.md").read_text()
    start = changelog.index("## v0.12.3.2")
    end = changelog.index("## v0.12.3.1.1", start)
    require("detached worktree" not in changelog[start:end], "obsolete v0.12.3.2 replay claim retained")

    roadmap = (root / "docs/ROADMAP.md").read_text()
    section_start = roadmap.index("## v0.12 - Production Readiness Capstone")
    section_end = roadmap.index("## v1.0 - Production-ready Commercial Baseline", section_start)
    section = roadmap[section_start:section_end]
    section_words = " ".join(section.split())
    require("v0.12.3.3 - CI feedback-efficiency closure" in section, "roadmap closure missing")
    require("runtime replay disabled" in section_words, "roadmap runtime boundary missing")


contract = load(contract_path)
validate(contract)

mutations = []


def mutate(path, replacement):
    candidate = deepcopy(contract)
    cursor = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    mutations.append(candidate)


mutate(["protectedMainBaselineCommit"], "0" * 40)
mutate(["measurements", "preRoutingFullGateElapsedSeconds"], 29)
mutate(["measurements", "convergedFullGateReportedElapsedSeconds"], 302)
mutate(["measurements", "convergedValidationLogSha256"], "0" * 64)
mutate(["measurements", "performanceSlaClaimed"], True)
mutate(["convergence", "stableRequiredQualityGatePreserved"], False)
mutate(["convergence", "coreAndAmbiguousChangesRemainFull"], False)
mutate(["convergence", "historicalEntrypointCount"], 111)
mutate(["convergence", "historicalRuntimeReplayExecuted"], True)
mutate(["convergence", "detachedHistoricalWorktreeCreated"], True)
mutate(["evidenceBoundary", "postMergeGithubRunRecordedInRepository"], True)
mutate(["terraformRecoveryBoundary", "reviewedRefreshOnlyApplyAlreadyExecuted"], False)
mutate(["terraformRecoveryBoundary", "expectedPersistedStateSerial"], 1)
mutate(["terraformRecoveryBoundary", "refreshOnlyApplyMayBeRetried"], True)
mutate(["terraformRecoveryBoundary", "stateRecoveryResumedByThisIncrement"], True)
mutate(["executionBoundary", "awsOperationAuthorized"], True)
mutate(["executionBoundary", "terraformApplyAuthorized"], True)
mutate(["executionBoundary", "automaticRetryAuthorized"], True)
mutate(["deferred", "repositoryPhysicalRestructure"], "v0.12.3.3")
for index, candidate in enumerate(mutations, 1):
    try:
        validate(candidate, check_repository=False)
    except (AttributeError, KeyError, TypeError, ClosureError):
        continue
    raise ClosureError(f"fail-open mutation {index}")

tracked_paths = [contract_path, document_path, validator_path]
tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
    capture_output=True,
    text=True,
    check=True,
).stdout.splitlines()
require(len(tracked) == len(tracked_paths), "closure source tracking drift")
modes = {}
for line in tracked:
    metadata, path = line.split("\t", 1)
    modes[path] = metadata.split()[0]
require(modes[str(contract_path.relative_to(root))] == "100644", "contract mode drift")
require(modes[str(document_path.relative_to(root))] == "100644", "document mode drift")
require(modes[str(validator_path.relative_to(root))] == "100755", "validator mode drift")

print(f"v0.12.3.3 CI feedback-efficiency closure and {len(mutations)} fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.3.4-promotion-lifecycle-closure.py" \
  --root "${ROOT_DIR}"

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh" \
  "${ROOT_DIR}/scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh"

if [[ "${mode}" == "--structure-only" ]]; then
  bash "${ROOT_DIR}/scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh" --structure-only
  echo "v0.12.3.4 structure-only promotion/lifecycle convergence closure passed; no live action was executed."
  exit 0
fi

bash "${ROOT_DIR}/scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh"
echo "v0.12.3.4 promotion/lifecycle convergence closure passed; no live action was executed."
