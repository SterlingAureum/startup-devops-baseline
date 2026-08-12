#!/usr/bin/env python3
"""Combine same-run static and trusted runtime results into durable evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from demo_api_qualification_bundle import canonical_bytes, utc, validate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--static-result", type=Path, required=True)
    parser.add_argument("--runtime-result", type=Path, required=True)
    parser.add_argument("--scope-result", type=Path, required=True)
    parser.add_argument("--control-plane-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--recorded-at")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    static = json.loads(args.static_result.read_text())
    runtime = json.loads(args.runtime_result.read_text())
    scope = json.loads(args.scope_result.read_text())
    recorded_at = utc(args.recorded_at) if args.recorded_at else datetime.now(timezone.utc).replace(microsecond=0)
    static_recorded = utc(static["qualification"]["recordedAt"])
    static_expires = static_recorded + timedelta(days=7)
    runtime_expires = utc(runtime["expiresAt"])
    expires_at = min(static_expires, runtime_expires)
    release = static["release"]
    identity = {
        field: release[field]
        for field in ("sourceRepository", "sourceCommit", "imageRepository", "imageTag", "imageDigest", "buildWorkflowRunId")
    }
    release_id = (
        f"demo-api-{identity['sourceCommit'][:12]}-"
        f"{identity['imageDigest'].removeprefix('sha256:')[:12]}"
    )
    document = {
        "schemaVersion": "v0.10.4",
        "application": "demo-api",
        "environment": "aws-dev",
        "releaseId": release_id,
        "status": "qualified",
        "recordedAt": recorded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity,
        "release": {
            "path": "apps/demo-api/helm/values/releases/aws-dev.yaml",
            "sha256": release["sha256"],
        },
        "qualificationScope": {
            field: scope[field]
            for field in ("algorithm", "contract", "contractSha256", "scopeSha256", "files")
        },
        "staticQualification": {
            "sha256": hashlib.sha256(canonical_bytes(static)).hexdigest(),
            "expiresAt": static_expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result": static,
        },
        "runtimeQualification": {
            "sha256": hashlib.sha256(canonical_bytes(runtime)).hexdigest(),
            "result": runtime,
        },
        "orchestration": {
            "repository": "SterlingAureum/startup-devops-baseline",
            "ref": "refs/heads/main",
            "revision": args.control_plane_sha,
            "workflow": ".github/workflows/demo-api-release-orchestrator.yaml",
            "workflowRunId": args.workflow_run_id,
            "workflowRunAttempt": args.workflow_run_attempt,
            "actor": args.actor,
        },
    }
    validate(document, root=args.root, now=recorded_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(document))
    print(args.output)


if __name__ == "__main__":
    main()
