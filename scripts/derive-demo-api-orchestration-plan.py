#!/usr/bin/env python3
"""Derive one deterministic demo-api decision with bounded aws-dev execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ENVIRONMENTS = ("aws-dev", "aws-test", "aws-prod")
OPERATIONS = ("start", "status", "resume")
RELEASE_ID_PATTERN = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def fail(message: str) -> None:
    raise SystemExit(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def validate_identity(identity: dict[str, Any]) -> None:
    required = {
        "releaseId",
        "sourceRepository",
        "sourceCommit",
        "imageRepository",
        "imageTag",
        "imageDigest",
        "buildWorkflowRunId",
    }
    require(set(identity) == required, "Release identity fields are incomplete")
    require(RELEASE_ID_PATTERN.fullmatch(identity["releaseId"]) is not None, "Invalid release ID")
    require(SHA_PATTERN.fullmatch(identity["sourceCommit"]) is not None, "Invalid source commit")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", identity["imageDigest"]) is not None, "Invalid digest")
    expected = (
        f"demo-api-{identity['sourceCommit'][:12]}-"
        f"{identity['imageDigest'].removeprefix('sha256:')[:12]}"
    )
    require(identity["releaseId"] == expected, "Release ID differs from immutable identity")
    require(identity["imageTag"] == f"sha-{identity['sourceCommit'][:7]}", "Image tag differs from source")
    require(re.fullmatch(r"[0-9]+", identity["buildWorkflowRunId"]) is not None, "Invalid build run ID")


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "application",
        "operation",
        "policy",
        "trigger",
        "capturedMainRevision",
        "observedMainRevision",
        "requestedReleaseId",
        "activeRelease",
        "releases",
        "evidence",
        "qualificationBundles",
        "pullRequests",
        "environmentAvailability",
        "derivedAt",
    }
    require(set(snapshot) == required, "Snapshot fields are missing or unknown")
    require(snapshot["schemaVersion"] == "v0.10.4", "Unsupported snapshot schema")
    require(snapshot["application"] == "demo-api", "Unexpected application")
    require(snapshot["operation"] in OPERATIONS, "Unsupported operation")
    require(snapshot["policy"] in {"reviewed", "continuous-nonprod"}, "Unsupported policy")
    require(snapshot["trigger"].get("ref") == "refs/heads/main", "Only protected main may be orchestrated")
    require(SHA_PATTERN.fullmatch(snapshot["capturedMainRevision"]) is not None, "Invalid captured main")
    require(SHA_PATTERN.fullmatch(snapshot["observedMainRevision"]) is not None, "Invalid observed main")
    if snapshot["requestedReleaseId"] is not None:
        require(RELEASE_ID_PATTERN.fullmatch(snapshot["requestedReleaseId"]) is not None, "Bad requested release ID")
    if snapshot["activeRelease"] is not None:
        validate_identity(snapshot["activeRelease"])
    require(set(snapshot["releases"]) == set(ENVIRONMENTS), "Release environment set changed")
    for environment, fact in snapshot["releases"].items():
        require(fact["path"] == f"apps/demo-api/helm/values/releases/{environment}.yaml", "Wrong release path")
        require(re.fullmatch(r"[0-9a-f]{64}", fact["sha256"]) is not None, "Bad release hash")
        validate_identity(fact["identity"])
    require(set(snapshot["evidence"]) == {"aws-dev", "aws-test"}, "Evidence environment set changed")
    for pair in snapshot["evidence"].values():
        require(set(pair) == {"static", "runtime"}, "Evidence pair is incomplete")
        for fact in pair.values():
            require(fact.get("state") in {"missing", "fresh", "stale"}, "Bad evidence state")
    require(set(snapshot["qualificationBundles"]) == {"aws-dev"}, "Qualification Bundle environment set changed")
    require(snapshot["qualificationBundles"]["aws-dev"].get("state") in {"missing", "fresh", "stale"}, "Bad Qualification Bundle state")
    require(set(snapshot["environmentAvailability"]) == set(ENVIRONMENTS), "Availability set changed")
    for value in snapshot["environmentAvailability"].values():
        require(value in {"present", "absent", "unknown"}, "Bad environment availability")
    for pr in snapshot["pullRequests"]:
        require(pr.get("baseRefName") == "main", "Discovered PR does not target main")
        require(pr.get("targetEnvironment") in ENVIRONMENTS, "Discovered PR has bad environment")
        require(pr.get("kind") in {"environment-release", "static-evidence", "runtime-evidence", "qualification-bundle"}, "Bad PR kind")
        require(RELEASE_ID_PATTERN.fullmatch(pr.get("releaseId", "")) is not None, "PR lacks release identity")
        require(re.fullmatch(r"[0-9a-f]{64}", pr.get("releaseSha256", "")) is not None, "PR lacks release hash")


def matches_release(snapshot: dict[str, Any], environment: str, release_id: str) -> bool:
    return snapshot["releases"][environment]["identity"]["releaseId"] == release_id


def open_pr(
    snapshot: dict[str, Any],
    release_id: str,
    environment: str,
    kinds: set[str],
) -> dict[str, Any] | None:
    matches = [
        pr
        for pr in snapshot["pullRequests"]
        if pr["releaseId"] == release_id
        and pr["targetEnvironment"] == environment
        and pr["kind"] in kinds
        and (
            pr["kind"] == "environment-release"
            or pr["releaseSha256"] == snapshot["releases"][environment]["sha256"]
        )
    ]
    if len(matches) > 1:
        fail(
            f"Duplicate open PRs discovered for {release_id} {environment}: "
            + ", ".join(f"#{item['number']}" for item in matches)
        )
    return matches[0] if matches else None


def decision(
    snapshot: dict[str, Any],
    phase: str,
    status: str,
    reason: str | None,
    action: str,
    target: str | None,
    pr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = snapshot["activeRelease"]
    return {
        "schemaVersion": "v0.10.4",
        "application": "demo-api",
        "operation": snapshot["operation"],
        "releaseId": active["releaseId"] if active else None,
        "phase": phase,
        "status": status,
        "reason": reason,
        "recommendedAction": action,
        "targetEnvironment": target,
        "openPullRequest": {"number": pr["number"], "url": pr["url"]} if pr else None,
        "executionMode": "aws-dev-qualification",
        "dispatchAuthorized": action == "qualify-aws-dev" and target == "aws-dev",
        "capturedMainRevision": snapshot["capturedMainRevision"],
        "observedMainRevision": snapshot["observedMainRevision"],
        "derivedAt": snapshot["derivedAt"],
    }


def qualify_environment(
    snapshot: dict[str, Any], environment: str, phase: str, release_id: str, use_bundle: bool = False
) -> dict[str, Any] | None:
    if snapshot["environmentAvailability"][environment] == "absent":
        return decision(
            snapshot,
            phase,
            "waiting_environment",
            "environment-absent",
            "restore-environment",
            environment,
        )
    evidence_pr = open_pr(
        snapshot,
        release_id,
        environment,
        {"qualification-bundle"} if use_bundle else {"static-evidence", "runtime-evidence"},
    )
    if evidence_pr:
        return decision(
            snapshot,
            phase,
            "waiting_review",
            "review-required",
            "wait-for-review",
            environment,
            evidence_pr,
        )
    if use_bundle:
        bundle = snapshot["qualificationBundles"]["aws-dev"]
        if bundle["state"] == "stale":
            return decision(
                snapshot,
                phase,
                "blocked",
                "qualification-stale",
                "qualify-aws-dev",
                environment,
            )
        if bundle["state"] == "missing":
            return decision(
                snapshot,
                phase,
                "progressing",
                "qualification-missing",
                "qualify-aws-dev",
                environment,
            )
        return None

    runtime = snapshot["evidence"][environment]["runtime"]
    static = snapshot["evidence"][environment]["static"]
    if runtime["state"] == "stale" or static["state"] == "stale":
        action = "collect-runtime-evidence" if runtime["state"] == "stale" else "record-static-evidence"
        return decision(
            snapshot,
            phase,
            "blocked",
            "qualification-stale",
            action,
            environment,
        )
    if runtime["state"] == "missing":
        return decision(
            snapshot,
            phase,
            "waiting_runtime",
            "runtime-executor-unavailable",
            "collect-runtime-evidence",
            environment,
        )
    if static["state"] == "missing":
        return decision(
            snapshot,
            phase,
            "progressing",
            "qualification-missing",
            "record-static-evidence",
            environment,
        )
    return None


def derive(snapshot: dict[str, Any]) -> dict[str, Any]:
    validate_snapshot(snapshot)
    if snapshot["capturedMainRevision"] != snapshot["observedMainRevision"]:
        return decision(
            snapshot,
            "source" if snapshot["activeRelease"] is None else "image",
            "blocked",
            "stale-main",
            "retry-after-main-stabilizes",
            None,
        )

    active = snapshot["activeRelease"]
    if active is None:
        return decision(
            snapshot,
            "source",
            "progressing",
            "image-pending",
            "publish-image-and-prepare-dev",
            "aws-dev",
        )

    release_id = active["releaseId"]
    if matches_release(snapshot, "aws-prod", release_id):
        return decision(snapshot, "complete", "completed", None, "none", None)

    dev_pr = open_pr(snapshot, release_id, "aws-dev", {"environment-release"})
    if not matches_release(snapshot, "aws-dev", release_id):
        if dev_pr:
            return decision(
                snapshot,
                "dev-release",
                "waiting_review",
                "review-required",
                "wait-for-review",
                "aws-dev",
                dev_pr,
            )
        return decision(
            snapshot,
            "image",
            "progressing",
            None,
            "prepare-dev-release",
            "aws-dev",
        )

    if not matches_release(snapshot, "aws-test", release_id):
        dev_qualification = qualify_environment(
            snapshot, "aws-dev", "dev-qualification", release_id, use_bundle=True
        )
        if dev_qualification:
            return dev_qualification
        test_pr = open_pr(snapshot, release_id, "aws-test", {"environment-release"})
        if test_pr:
            return decision(
                snapshot,
                "test-release",
                "waiting_review",
                "review-required",
                "wait-for-review",
                "aws-test",
                test_pr,
            )
        return decision(
            snapshot,
            "test-release",
            "progressing",
            None,
            "prepare-test-promotion",
            "aws-test",
        )

    test_qualification = qualify_environment(snapshot, "aws-test", "test-qualification", release_id)
    if test_qualification:
        return test_qualification

    prod_pr = open_pr(snapshot, release_id, "aws-prod", {"environment-release"})
    if not matches_release(snapshot, "aws-prod", release_id):
        if prod_pr:
            return decision(
                snapshot,
                "prod-release",
                "waiting_review",
                "review-required",
                "wait-for-review",
                "aws-prod",
                prod_pr,
            )
        return decision(
            snapshot,
            "prod-approval",
            "waiting_review",
            "review-required",
            "prepare-prod-promotion",
            "aws-prod",
        )

    return decision(snapshot, "prod-release", "blocked", "policy-violation", "none", "aws-prod")


def write_github_output(path: Path, value: dict[str, Any]) -> None:
    with path.open("a") as output:
        for key in (
            "releaseId",
            "phase",
            "status",
            "reason",
            "recommendedAction",
            "targetEnvironment",
        ):
            output_name = re.sub(r"(?<!^)(?=[A-Z])", "-", key).lower()
            rendered = value[key]
            output.write(f"{output_name}={'' if rendered is None else rendered}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    value = derive(snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    if args.github_output:
        write_github_output(args.github_output, value)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
