#!/usr/bin/env python3
"""Validate the reviewed aws-dev live contract against its release identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_EVIDENCE_VERSION = "v0.11.9.3.6.5.2"
EXPECTED_EXECUTION_COMMIT = "489c8036b21ee465160a1de0973a24b95b73dbfb"
EXPECTED_EXECUTION_RESULT_SHA256 = "2d56815b00bbcd050966b761828a093ee9fee7ab0aa63b15c77ebfa967c07d61"
EXPECTED_RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"
EXPECTED_SOURCE_COMMIT = "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
EXPECTED_IMAGE_DIGEST = "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623"
EXPECTED_IMAGE_REPOSITORY = "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api"
EXPECTED_SOURCE_REPOSITORY = "SterlingAureum/startup-devops-baseline"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read reviewed live contract: {error}") from error
    require(isinstance(value, dict), "Reviewed live contract must be a JSON object")
    return value


def decode_scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        decoded = json.loads(value)
        require(isinstance(decoded, str), "Release scalar must be a string")
        return decoded
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_release(path: Path) -> dict[tuple[str, str], str]:
    expected_fields = {
        ("image", "repository"),
        ("image", "tag"),
        ("image", "digest"),
        ("release", "applicationVersion"),
        ("delivery", "sourceRepository"),
        ("delivery", "sourceCommit"),
        ("delivery", "workflowRunId"),
    }
    values: dict[tuple[str, str], str] = {}
    sections: set[str] = set()
    section = ""
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise ValueError(f"Could not read source release: {error}") from error
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            require(section not in sections, f"Duplicate release section at line {line_number}")
            sections.add(section)
            continue
        require(indent == 2 and bool(section) and ":" in stripped, f"Unsupported release structure at line {line_number}")
        key, raw_value = stripped.split(":", 1)
        field = (section, key)
        require(field not in values, f"Duplicate release field at line {line_number}")
        values[field] = decode_scalar(raw_value)
    require(sections == {"image", "release", "delivery"}, "Source release sections changed")
    require(set(values) == expected_fields, "Source release fields changed")
    return values


def validate_contract(contract: dict[str, Any], release_id: str) -> None:
    require(contract.get("schemaVersion") == EXPECTED_EVIDENCE_VERSION, "Reviewed evidence schema changed")
    require(contract.get("version") == EXPECTED_EVIDENCE_VERSION, "Reviewed evidence version changed")
    require(contract.get("status") == "aws-dev-runtime-qualification-execution-recorded", "Reviewed evidence status is not accepted")
    require(contract.get("implementationBaselineCommit") == EXPECTED_EXECUTION_COMMIT, "Reviewed execution commit changed")
    require(contract.get("executionAuthorized") is False, "Evidence contract must not retain execution authorization")

    preflight = contract.get("preflight", {})
    require(preflight.get("executorExit") == 0, "Reviewed preflight did not exit successfully")
    require(preflight.get("controlPlaneCommit") == EXPECTED_EXECUTION_COMMIT, "Preflight commit changed")
    require(preflight.get("candidateReleaseId") == release_id, "Preflight release ID changed")
    require(preflight.get("executionAuthorized") is False, "Preflight unexpectedly authorized execution")
    require(preflight.get("trafficGenerated") is False, "Preflight unexpectedly generated traffic")
    require(preflight.get("runtimeQualified") is False, "Preflight unexpectedly claimed qualification")
    for key in ("demoDeploymentReady", "databaseReady", "grafanaDeploymentReady", "prometheusDemoTargetUp"):
        require(preflight.get(key) is True, f"Preflight readiness changed: {key}")

    execution = contract.get("execution", {})
    require(execution.get("executorExit") == 0, "Reviewed execution did not exit successfully")
    require(execution.get("status") == "aws-dev-runtime-qualification-complete", "Runtime qualification is incomplete")
    require(execution.get("controlPlaneCommit") == EXPECTED_EXECUTION_COMMIT, "Execution commit changed")
    require(execution.get("candidateReleaseId") == release_id, "Execution release ID changed")
    require(execution.get("boundedRequestCount") == 54, "Bounded request count changed")
    for key in ("trafficGenerated", "runtimeQualified", "requestSeriesReady", "availabilitySloPassed", "latencySloPassed", "finalRuntimeHealthy"):
        require(execution.get(key) is True, f"Accepted execution result changed: {key}")
    for key in ("criticalAlertsFiring", "progressiveDeliveryPromoted", "automaticTeardownExecuted"):
        require(execution.get(key) is False, f"Rejected execution result changed: {key}")
    require(execution.get("privateResultSha256") == EXPECTED_EXECUTION_RESULT_SHA256, "Execution result SHA-256 changed")

    operation = contract.get("operationBoundary", {})
    require(operation.get("runtimeQualificationExecuted") is True, "Runtime qualification boundary changed")
    require(operation.get("boundedNormalTrafficGenerated") is True, "Normal traffic boundary changed")
    for key in ("faultInjected", "rootOrMonitoringChanged", "rolloutOrAnalysisRunExecuted", "progressiveDeliveryPromoted", "awsTestPromotionExecuted", "teardownExecuted"):
        require(operation.get(key) is False, f"Operation boundary widened: {key}")


def validate_release(values: dict[tuple[str, str], str], release_id: str) -> None:
    repository = values[("image", "repository")]
    tag = values[("image", "tag")]
    digest = values[("image", "digest")]
    application_version = values[("release", "applicationVersion")]
    source_repository = values[("delivery", "sourceRepository")]
    source_commit = values[("delivery", "sourceCommit")]

    require(repository == EXPECTED_IMAGE_REPOSITORY, "Source image repository changed")
    require(source_repository == EXPECTED_SOURCE_REPOSITORY, "Source repository changed")
    require(COMMIT_RE.fullmatch(source_commit) is not None, "Source commit is invalid")
    require(DIGEST_RE.fullmatch(digest) is not None, "Source digest is invalid")
    require(source_commit == EXPECTED_SOURCE_COMMIT, "Source commit differs from reviewed execution")
    require(digest == EXPECTED_IMAGE_DIGEST, "Source digest differs from reviewed execution")
    require(tag == f"sha-{source_commit[:7]}", "Source tag differs from source commit")
    require(application_version == tag, "Application version differs from image tag")
    derived_release_id = f"demo-api-{source_commit[:12]}-{digest.removeprefix('sha256:')[:12]}"
    require(derived_release_id == release_id == EXPECTED_RELEASE_ID, "Source release ID differs from reviewed execution")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-contract", required=True, type=Path)
    parser.add_argument("--release-file", required=True, type=Path)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--expected-release-id", required=True)
    args = parser.parse_args()

    try:
        require(SHA256_RE.fullmatch(args.expected_contract_sha256) is not None, "Expected contract SHA-256 is invalid")
        require(SHA256_RE.fullmatch(args.expected_release_sha256) is not None, "Expected release SHA-256 is invalid")
        require(sha256(args.evidence_contract) == args.expected_contract_sha256, "Reviewed live contract SHA-256 changed")
        require(sha256(args.release_file) == args.expected_release_sha256, "Source release SHA-256 changed")
        contract = load_json(args.evidence_contract)
        validate_contract(contract, args.expected_release_id)
        validate_release(read_release(args.release_file), args.expected_release_id)
    except ValueError as error:
        parser.exit(1, f"Reviewed aws-dev qualification rejected: {error}\n")

    print("Reviewed aws-dev live qualification and immutable release identity accepted for release-only promotion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
