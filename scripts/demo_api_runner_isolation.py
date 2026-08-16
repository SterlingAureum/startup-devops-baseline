#!/usr/bin/env python3
"""Validate distinct ephemeral runner registrations for interruption recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


WORKFLOW_PATH = ".github/workflows/demo-api-release-orchestrator.yaml"
REQUIRED_LABELS = {"self-hosted", "linux", "x64", "trusted-runtime"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run_fact(run: dict[str, Any], expected_id: str, expected_conclusion: str) -> dict[str, Any]:
    require(str(run.get("id")) == expected_id, "Workflow run identity differs from the request.")
    require(run.get("path") == WORKFLOW_PATH, "Run is not the demo-api release orchestrator.")
    require(run.get("event") == "workflow_dispatch", "Recovery proof must use a manual workflow dispatch.")
    require(run.get("head_branch") == "main", "Recovery proof must target protected main.")
    require(run.get("status") == "completed", "Workflow run is not complete.")
    require(run.get("conclusion") == expected_conclusion, f"Workflow run must conclude {expected_conclusion}.")
    attempt = run.get("run_attempt")
    require(isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0, "Invalid workflow run attempt.")
    return {"runId": expected_id, "runAttempt": attempt}


def runtime_job(jobs: dict[str, Any], environment: str, interrupted: bool) -> dict[str, Any]:
    expected_name = f"Qualify {environment} from a trusted executor"
    matches = []
    for job in jobs.get("jobs", []):
        labels = set(job.get("labels") or [])
        if expected_name in str(job.get("name", "")) and REQUIRED_LABELS | {environment} <= labels:
            matches.append(job)
    require(len(matches) == 1, f"Expected exactly one trusted {environment} runtime Job, found {len(matches)}.")
    job = matches[0]
    runner_id = job.get("runner_id")
    require(isinstance(runner_id, int) and not isinstance(runner_id, bool) and runner_id > 0, "Runtime Job lacks a positive runner_id.")
    conclusion = job.get("conclusion")
    allowed = {"success", "cancelled"} if interrupted else {"success"}
    require(conclusion in allowed, f"Unexpected trusted runtime Job conclusion: {conclusion}.")
    runner_name = job.get("runner_name")
    require(isinstance(runner_name, str) and runner_name, "Runtime Job lacks a runner name.")
    return {
        "runnerId": runner_id,
        "runnerName": runner_name,
        "jobConclusion": conclusion,
    }


def validate(
    *,
    repository: str,
    environment: str,
    interrupted_run_id: str,
    resumed_run_id: str,
    interrupted_run: dict[str, Any],
    interrupted_jobs: dict[str, Any],
    resumed_run: dict[str, Any],
    resumed_jobs: dict[str, Any],
    registered_runners: dict[str, Any],
    require_unregistered: bool = True,
) -> dict[str, Any]:
    require(repository == "SterlingAureum/startup-devops-baseline", "Unexpected repository.")
    require(environment in {"aws-dev", "aws-test"}, "Runner isolation supports aws-dev/aws-test only.")
    require(interrupted_run_id.isdigit() and not interrupted_run_id.startswith("0"), "Invalid interrupted run ID.")
    require(resumed_run_id.isdigit() and not resumed_run_id.startswith("0"), "Invalid resumed run ID.")
    require(interrupted_run_id != resumed_run_id, "Interrupted and resumed workflow run IDs must differ.")

    interrupted = {
        **run_fact(interrupted_run, interrupted_run_id, "cancelled"),
        **runtime_job(interrupted_jobs, environment, interrupted=True),
    }
    resumed = {
        **run_fact(resumed_run, resumed_run_id, "success"),
        **runtime_job(resumed_jobs, environment, interrupted=False),
    }
    require(
        interrupted["runnerId"] != resumed["runnerId"],
        "Interrupted and resumed Jobs reused the same registered runner_id.",
    )

    registered_ids = {
        runner.get("id")
        for runner in registered_runners.get("runners", [])
        if isinstance(runner.get("id"), int)
    }
    if require_unregistered:
        require(interrupted["runnerId"] not in registered_ids, "Interrupted runner remains registered.")
        require(resumed["runnerId"] not in registered_ids, "Resumed runner remains registered.")

    return {
        "schemaVersion": "v0.10.8-runner-isolation",
        "repository": repository,
        "environment": environment,
        "status": "passed",
        "verifiedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "automaticUnregistrationVerified": require_unregistered,
        "interrupted": interrupted,
        "resumed": resumed,
    }
