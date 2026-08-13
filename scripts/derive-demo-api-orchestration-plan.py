#!/usr/bin/env python3
"""Derive one deterministic demo-api decision with bounded dev/test execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ENVIRONMENTS = ("aws-dev", "aws-test", "aws-prod")
OPERATIONS = ("start", "status", "resume", "retry")
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
        "retryAttempt",
        "testRolloutGate",
        "activeRelease",
        "releaseOrderState",
        "supersedingRelease",
        "releases",
        "evidence",
        "qualificationBundles",
        "pullRequests",
        "environmentAvailability",
        "derivedAt",
    }
    require(set(snapshot) == required, "Snapshot fields are missing or unknown")
    require(snapshot["schemaVersion"] == "v0.10.7", "Unsupported snapshot schema")
    require(snapshot["application"] == "demo-api", "Unexpected application")
    require(snapshot["operation"] in OPERATIONS, "Unsupported operation")
    require(snapshot["policy"] in {"reviewed", "continuous-nonprod"}, "Unsupported policy")
    require(snapshot["trigger"].get("ref") == "refs/heads/main", "Only protected main may be orchestrated")
    require(SHA_PATTERN.fullmatch(snapshot["capturedMainRevision"]) is not None, "Invalid captured main")
    require(SHA_PATTERN.fullmatch(snapshot["observedMainRevision"]) is not None, "Invalid observed main")
    if snapshot["requestedReleaseId"] is not None:
        require(RELEASE_ID_PATTERN.fullmatch(snapshot["requestedReleaseId"]) is not None, "Bad requested release ID")
    retry_attempt = snapshot["retryAttempt"]
    if snapshot["operation"] == "retry":
        require(isinstance(retry_attempt, dict), "retry lacks a validated prior Attempt")
        require(set(retry_attempt) == {
            "runId", "runAttempt", "releaseId", "outcome", "retryClass",
            "recommendedAction", "controlPlaneSha",
        }, "Invalid retry Attempt summary")
        require(retry_attempt["releaseId"] == snapshot["requestedReleaseId"], "Retry release mismatch")
        require(retry_attempt["outcome"] in {"blocked", "failed"}, "Retry source is not failed or blocked")
        require(retry_attempt["retryClass"] == "safe-new-attempt", "Retry source is not safely retryable")
        require(SHA_PATTERN.fullmatch(retry_attempt["controlPlaneSha"]) is not None, "Invalid retry control plane")
    else:
        require(retry_attempt is None, "Non-retry snapshot cites a prior Attempt")
    require(
        snapshot["testRolloutGate"] in {"not-reviewed", "reviewed-and-completed"},
        "Invalid aws-test Rollout gate",
    )
    if snapshot["activeRelease"] is not None:
        validate_identity(snapshot["activeRelease"])
    require(snapshot["releaseOrderState"] in {"current", "superseded", "ambiguous"}, "Bad release order state")
    if snapshot["supersedingRelease"] is not None:
        validate_identity(snapshot["supersedingRelease"])
    require(
        (snapshot["releaseOrderState"] == "superseded") == (snapshot["supersedingRelease"] is not None),
        "Supersede identity and state disagree",
    )
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
    require(set(snapshot["qualificationBundles"]) == {"aws-dev", "aws-test"}, "Qualification Bundle environment set changed")
    for bundle in snapshot["qualificationBundles"].values():
        require(bundle.get("state") in {
            "missing", "fresh", "expiring", "expired", "scope_drift",
            "release_drift", "invalid",
        }, "Bad Qualification Bundle state")
        require(set(bundle) == {
            "state", "reason", "id", "ref", "sha256", "expiresAt", "remainingSeconds",
        }, "Bad Qualification Bundle fact")
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
        "schemaVersion": "v0.10.7",
        "application": "demo-api",
        "operation": snapshot["operation"],
        "releaseId": active["releaseId"] if active else None,
        "phase": phase,
        "status": status,
        "reason": reason,
        "recommendedAction": action,
        "targetEnvironment": target,
        "openPullRequest": {"number": pr["number"], "url": pr["url"]} if pr else None,
        "supersededByReleaseId": (
            snapshot["supersedingRelease"]["releaseId"]
            if snapshot["supersedingRelease"] is not None
            else None
        ),
        "executionMode": "bounded-reviewed-promotion",
        "dispatchAuthorized": (
            snapshot["operation"] != "status"
            and (
                snapshot["operation"] != "retry"
                or (
                    snapshot["retryAttempt"] is not None
                    and snapshot["retryAttempt"]["recommendedAction"] == action
                )
            )
            and (
                (action == "qualify-aws-dev" and target == "aws-dev")
                or (action == "prepare-test-promotion" and target == "aws-test")
                or (action == "qualify-aws-test" and target == "aws-test")
                or (action == "prepare-prod-promotion" and target == "aws-prod")
            )
        ),
        "capturedMainRevision": snapshot["capturedMainRevision"],
        "observedMainRevision": snapshot["observedMainRevision"],
        "derivedAt": snapshot["derivedAt"],
    }


def qualify_environment(
    snapshot: dict[str, Any], environment: str, phase: str, release_id: str
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
        {"qualification-bundle"},
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
    bundle = snapshot["qualificationBundles"][environment]
    action = "qualify-aws-dev" if environment == "aws-dev" else "qualify-aws-test"
    if bundle["state"] == "invalid":
        return decision(
            snapshot,
            phase,
            "blocked",
            "qualification-invalid",
            "none",
            environment,
        )
    if bundle["state"] != "fresh":
        return decision(
            snapshot,
            phase,
            "progressing",
            f"qualification-{bundle['state'].replace('_', '-')}",
            action,
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

    if snapshot["operation"] == "retry" and snapshot["retryAttempt"]["controlPlaneSha"] != snapshot["capturedMainRevision"]:
        return decision(
            snapshot,
            "image",
            "blocked",
            "retry-control-plane-changed",
            "none",
            None,
        )
    if snapshot["releaseOrderState"] == "ambiguous":
        return decision(
            snapshot,
            "image",
            "blocked",
            "release-order-ambiguous",
            "none",
            None,
        )
    if snapshot["releaseOrderState"] == "superseded":
        return decision(
            snapshot,
            "image",
            "superseded",
            "newer-release-active",
            "review-and-close-superseded-pr",
            None,
        )

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
        dev_qualification = qualify_environment(snapshot, "aws-dev", "dev-qualification", release_id)
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

    test_bundle_pr = open_pr(snapshot, release_id, "aws-test", {"qualification-bundle"})
    if test_bundle_pr:
        return decision(
            snapshot,
            "test-qualification",
            "waiting_review",
            "review-required",
            "wait-for-review",
            "aws-test",
            test_bundle_pr,
        )
    if snapshot["qualificationBundles"]["aws-test"]["state"] != "fresh":
        if snapshot["environmentAvailability"]["aws-test"] == "absent":
            return decision(
                snapshot,
                "test-qualification",
                "waiting_environment",
                "environment-absent",
                "restore-environment",
                "aws-test",
            )
        if snapshot["testRolloutGate"] != "reviewed-and-completed":
            return decision(
                snapshot,
                "test-qualification",
                "waiting_review",
                "canary-review-required",
                "review-and-complete-test-canary",
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
            "production-environment-approval-required",
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
