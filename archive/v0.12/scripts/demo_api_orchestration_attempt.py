#!/usr/bin/env python3
"""Validate and classify secret-free v0.10.7 orchestration attempts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
INTEGER = re.compile(r"^[1-9][0-9]*$")
SENSITIVE = re.compile(
    r"(?:^|[-_])(secret|token|credential|password|kubeconfig)(?:$|[-_])",
    re.IGNORECASE,
)

OUTCOMES = {
    "succeeded", "waiting", "blocked", "failed", "superseded", "no_action",
    "automation_disabled",
}
RETRY_CLASSES = {"none", "safe-new-attempt", "resume-after-change", "manual-investigation"}
RUNTIME_RETRY = {
    "environment_absent": "resume-after-change",
    "main_advanced": "resume-after-change",
    "oidc_denied": "resume-after-change",
    "endpoint_unreachable": "safe-new-attempt",
    "executor_unavailable": "safe-new-attempt",
    "argo_not_converged": "safe-new-attempt",
    "https_validation_failed": "manual-investigation",
    "rollout_unhealthy": "manual-investigation",
    "analysis_failed": "manual-investigation",
    "digest_mismatch": "manual-investigation",
    "rbac_boundary_failed": "manual-investigation",
    "input_mismatch": "manual-investigation",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def reject_sensitive(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(not SENSITIVE.search(str(key)), f"Forbidden sensitive attempt field: {path}.{key}")
            reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive(child, f"{path}[{index}]")


def validate(document: dict[str, Any]) -> None:
    top = {
        "schemaVersion", "application", "releaseId", "operation", "controlPlaneSha",
        "run", "decision", "execution", "retryOf", "rollbackHandoff", "startedAt",
        "completedAt",
    }
    require(set(document) == top, "Attempt has missing or unknown top-level fields.")
    require(document["schemaVersion"] == "v0.10.7", "Unsupported Attempt schema.")
    require(document["application"] == "demo-api", "Unexpected Attempt application.")
    release_id = document["releaseId"]
    require(release_id is None or RELEASE_ID.fullmatch(release_id) is not None, "Invalid Attempt Release ID.")
    require(document["operation"] in {"start", "status", "resume", "retry"}, "Invalid Attempt operation.")
    require(SHA.fullmatch(document["controlPlaneSha"]) is not None, "Invalid Attempt control-plane SHA.")

    run = document["run"]
    require(set(run) == {"repository", "workflow", "id", "attempt", "actor", "url"}, "Invalid Attempt run identity.")
    require(run["workflow"] == ".github/workflows/demo-api-release-orchestrator.yaml", "Unexpected Attempt workflow.")
    require(INTEGER.fullmatch(str(run["id"])) is not None, "Invalid Attempt run ID.")
    require(isinstance(run["attempt"], int) and run["attempt"] > 0, "Invalid Attempt run number.")
    require(all(isinstance(run[key], str) and run[key] for key in ("repository", "actor", "url")), "Incomplete Attempt run identity.")

    decision = document["decision"]
    require(set(decision) == {"phase", "status", "recommendedAction", "targetEnvironment", "dispatchAuthorized"}, "Invalid Attempt decision.")
    require(decision["targetEnvironment"] in {None, "aws-dev", "aws-test", "aws-prod"}, "Invalid Attempt target.")
    require(isinstance(decision["dispatchAuthorized"], bool), "Invalid dispatch flag.")
    if document["operation"] == "status":
        require(not decision["dispatchAuthorized"], "status must never authorize execution.")

    execution = document["execution"]
    require(set(execution) == {"stage", "outcome", "reason", "retryClass", "recommendedRecovery", "stageResult"}, "Invalid Attempt execution.")
    require(execution["outcome"] in OUTCOMES, "Invalid Attempt outcome.")
    require(execution["retryClass"] in RETRY_CLASSES, "Invalid Attempt retry class.")
    require(isinstance(execution["stageResult"], dict), "Attempt stage result must be an object.")
    if execution["outcome"] not in {"blocked", "failed"}:
        require(execution["retryClass"] == "none", "Only blocked or failed Attempts may be retried.")

    retry_of = document["retryOf"]
    if document["operation"] == "retry":
        require(isinstance(retry_of, dict), "retry must cite a prior Attempt.")
    else:
        require(retry_of is None, "Only retry may cite a prior Attempt.")
    if retry_of is not None:
        require(set(retry_of) == {"runId", "runAttempt"}, "Invalid retry lineage.")
        require(INTEGER.fullmatch(str(retry_of["runId"])) is not None, "Invalid retry run ID.")
        require(isinstance(retry_of["runAttempt"], int) and retry_of["runAttempt"] > 0, "Invalid retry run attempt.")

    handoff = document["rollbackHandoff"]
    if handoff is not None:
        expected = {
            "targetEnvironment", "failedReleaseId", "currentReleaseSha256",
            "rollbackToRevision", "previousReleaseId", "previousImageDigest",
            "failureReason", "manualWorkflowCommand",
        }
        require(set(handoff) == expected, "Invalid rollback handoff.")
        require(handoff["targetEnvironment"] in {"aws-dev", "aws-test"}, "Production handoff is not orchestrated.")
        require(RELEASE_ID.fullmatch(handoff["failedReleaseId"]) is not None, "Invalid failed release.")
        require(SHA256.fullmatch(handoff["currentReleaseSha256"]) is not None, "Invalid current release hash.")
        require(SHA.fullmatch(handoff["rollbackToRevision"]) is not None, "Invalid rollback revision.")
        require(RELEASE_ID.fullmatch(handoff["previousReleaseId"]) is not None, "Invalid previous Release ID.")
        require(DIGEST.fullmatch(handoff["previousImageDigest"]) is not None, "Invalid previous digest.")
        require(execution["outcome"] == "failed", "Rollback handoff requires a failed Attempt.")
        require(handoff["failedReleaseId"] == release_id, "Rollback handoff release mismatch.")

    started = utc(document["startedAt"])
    completed = utc(document["completedAt"])
    require(started <= completed, "Attempt completed before it started.")
    reject_sensitive(document)


def classify(
    operation: str,
    decision: dict[str, Any],
    stages: dict[str, Any],
) -> dict[str, Any]:
    action = decision["recommendedAction"]
    if decision["status"] == "superseded":
        return {
            "stage": "derive", "outcome": "superseded", "reason": decision.get("reason") or "newer-release-active",
            "retryClass": "none", "recommendedRecovery": "review-and-close-superseded-pr", "stageResult": stages,
        }
    if operation == "status":
        return {
            "stage": "derive", "outcome": "no_action", "reason": "read-only-status",
            "retryClass": "none", "recommendedRecovery": action, "stageResult": stages,
        }
    disabled = stages.get("disabled", {})
    if any(value == "success" for value in disabled.values()):
        return {
            "stage": "activation", "outcome": "automation_disabled", "reason": "activation-variable-disabled",
            "retryClass": "none", "recommendedRecovery": "enable-reviewed-variable-then-resume", "stageResult": stages,
        }
    runtime = stages.get("runtime", {})
    runtime_status = runtime.get("status", "")
    runtime_reason = runtime.get("reason", "")
    if runtime_status in {"blocked", "failed"} or runtime.get("result") == "failure":
        outcome = runtime_status if runtime_status in {"blocked", "failed"} else "failed"
        reason = runtime_reason or "runtime-stage-failed-without-result"
        retry_class = RUNTIME_RETRY.get(reason, "manual-investigation")
        recovery = {
            "safe-new-attempt": "retry",
            "resume-after-change": "correct-external-fact-then-resume",
            "manual-investigation": "investigate-then-retry-or-use-rollback-handoff",
        }[retry_class]
        return {
            "stage": "runtime-qualification", "outcome": outcome, "reason": reason,
            "retryClass": retry_class, "recommendedRecovery": recovery, "stageResult": stages,
        }
    mapping = {
        "prepare-test-promotion": "testPromotion",
        "prepare-prod-promotion": "prodPromotion",
        "qualify-aws-dev": "bundle",
        "qualify-aws-test": "bundle",
    }
    stage_key = mapping.get(action)
    if stage_key:
        stage = stages.get(stage_key, {})
        if stage.get("result") == "success":
            return {
                "stage": stage_key, "outcome": "succeeded", "reason": stage.get("status") or "stage-succeeded",
                "retryClass": "none", "recommendedRecovery": "wait-for-durable-git-fact", "stageResult": stages,
            }
        if decision["dispatchAuthorized"]:
            return {
                "stage": stage_key, "outcome": "failed", "reason": "stage-execution-failed",
                "retryClass": "safe-new-attempt", "recommendedRecovery": "retry", "stageResult": stages,
            }
    return {
        "stage": "derive", "outcome": "waiting", "reason": decision.get("reason") or "human-or-external-action-required",
        "retryClass": "none", "recommendedRecovery": action, "stageResult": stages,
    }


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    validate(value)
    return value
