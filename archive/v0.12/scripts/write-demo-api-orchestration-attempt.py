#!/usr/bin/env python3
"""Write one secret-free post-execution v0.10.7 Attempt artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from demo_api_orchestration_attempt import classify, validate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--stage-results", required=True, type=Path)
    parser.add_argument("--rollback-handoff", type=Path)
    parser.add_argument("--operation", required=True, choices=("start", "status", "resume", "retry"))
    parser.add_argument("--control-plane-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--retry-run-id")
    parser.add_argument("--retry-run-attempt", type=int)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--completed-at")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    decision = json.loads(args.decision.read_text())
    stages = json.loads(args.stage_results.read_text())
    execution = classify(args.operation, decision, stages)
    handoff = json.loads(args.rollback_handoff.read_text()) if args.rollback_handoff and args.rollback_handoff.is_file() else None
    completed_at = args.completed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    retry_of = None
    if args.operation == "retry":
        retry_of = {"runId": args.retry_run_id, "runAttempt": args.retry_run_attempt}
    document = {
        "schemaVersion": "v0.10.7",
        "application": "demo-api",
        "releaseId": decision["releaseId"],
        "operation": args.operation,
        "controlPlaneSha": args.control_plane_sha,
        "run": {
            "repository": args.repository,
            "workflow": ".github/workflows/demo-api-release-orchestrator.yaml",
            "id": str(args.run_id),
            "attempt": args.run_attempt,
            "actor": args.actor,
            "url": args.run_url,
        },
        "decision": {
            "phase": decision["phase"],
            "status": decision["status"],
            "recommendedAction": decision["recommendedAction"],
            "targetEnvironment": decision["targetEnvironment"],
            "dispatchAuthorized": decision["dispatchAuthorized"],
        },
        "execution": execution,
        "retryOf": retry_of,
        "rollbackHandoff": handoff,
        "startedAt": args.started_at,
        "completedAt": completed_at,
    }
    validate(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"Wrote orchestration Attempt: {args.output}")


if __name__ == "__main__":
    main()
