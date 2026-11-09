#!/usr/bin/env python3
"""Write one secret-free, release-bound runtime qualification result."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re


ENVIRONMENTS = {
    "aws-dev": {
        "github_environment": "aws-dev-runtime",
        "cluster": "startup-devops-baseline-dev",
        "argo_application": "demo-api-aws-dev",
        "workload_kind": "Deployment",
        "hostname": "demo.dev.aureumstack.com",
    },
    "aws-test": {
        "github_environment": "aws-test-runtime",
        "cluster": "startup-devops-baseline-test",
        "argo_application": "demo-api-aws-test",
        "workload_kind": "Rollout",
        "hostname": "demo.test.aureumstack.com",
    },
}

REASONS = {
    "qualified": {"all_checks_passed"},
    "blocked": {
        "environment_absent",
        "executor_unavailable",
        "main_advanced",
        "oidc_denied",
        "endpoint_unreachable",
    },
    "failed": {
        "input_mismatch",
        "argo_not_converged",
        "rollout_unhealthy",
        "analysis_failed",
        "digest_mismatch",
        "https_validation_failed",
        "rbac_boundary_failed",
    },
}

SENSITIVE_KEY = re.compile(
    r"(?:^|[-_])(secret|token|credential|password|kubeconfig)(?:$|[-_])",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--control-plane-sha", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-image-digest", required=True)
    parser.add_argument("--expected-release-file-sha256", required=True)
    parser.add_argument("--release-file", type=Path, required=True)
    parser.add_argument("--status", choices=sorted(REASONS), required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--runtime-facts", type=Path)
    parser.add_argument("--runner-name", default="")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--aws-caller-arn", default="")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_release(path: Path) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    section: str | None = None
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
        elif indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            field = (section, key)
            if field in values:
                raise SystemExit(f"{path}:{number}: duplicate {section}.{key}")
            values[field] = scalar(value)
        else:
            raise SystemExit(f"{path}:{number}: unsupported release values structure")
    return values


def reject_sensitive_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise SystemExit(f"Runtime result contains forbidden field: {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")


def main() -> None:
    args = parse_args()
    if args.environment not in ENVIRONMENTS:
        raise SystemExit("Runtime qualification permits only aws-dev and aws-test.")
    if args.reason not in REASONS[args.status]:
        raise SystemExit("Runtime qualification status and reason are inconsistent.")
    for name, value, pattern in (
        ("control plane SHA", args.control_plane_sha, r"[0-9a-f]{40}"),
        ("source commit", args.expected_source_commit, r"[0-9a-f]{40}"),
        ("image digest", args.expected_image_digest, r"sha256:[0-9a-f]{64}"),
        ("release file SHA-256", args.expected_release_file_sha256, r"[0-9a-f]{64}"),
        ("workflow run ID", args.workflow_run_id, r"[1-9][0-9]*"),
        ("workflow run attempt", args.workflow_run_attempt, r"[1-9][0-9]*"),
    ):
        if not re.fullmatch(pattern, value):
            raise SystemExit(f"Invalid {name}.")

    expected_release_id = (
        f"demo-api-{args.expected_source_commit[:12]}-"
        f"{args.expected_image_digest.removeprefix('sha256:')[:12]}"
    )
    if args.release_id != expected_release_id:
        raise SystemExit("Release ID does not match source commit and image digest.")
    if hashlib.sha256(args.release_file.read_bytes()).hexdigest() != args.expected_release_file_sha256:
        raise SystemExit("Release file SHA-256 differs from the requested release identity.")

    values = read_release(args.release_file)
    required = {
        ("image", "repository"),
        ("image", "tag"),
        ("image", "digest"),
        ("release", "applicationVersion"),
        ("delivery", "sourceRepository"),
        ("delivery", "sourceCommit"),
        ("delivery", "workflowRunId"),
    }
    if set(values) != required:
        raise SystemExit("Release values do not satisfy the isolated release schema.")
    repository = values[("image", "repository")]
    if repository != "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api":
        raise SystemExit("Unexpected image repository.")
    if values[("delivery", "sourceRepository")] != "SterlingAureum/startup-devops-baseline":
        raise SystemExit("Unexpected source repository.")
    if values[("delivery", "sourceCommit")] != args.expected_source_commit:
        raise SystemExit("Release source commit differs from the requested identity.")
    if values[("image", "digest")] != args.expected_image_digest:
        raise SystemExit("Release image digest differs from the requested identity.")

    environment = ENVIRONMENTS[args.environment]
    expected_release_file = f"apps/demo-api/helm/values/releases/{args.environment}.yaml"
    if args.release_file.name != f"{args.environment}.yaml":
        raise SystemExit("Release file name does not match the runtime environment.")
    runtime = {
        "argoApplication": environment["argo_application"],
        "argoRevision": "",
        "workloadKind": environment["workload_kind"],
        "workloadName": "demo-api",
        "rolloutPhase": "",
        "analysisRunName": "",
        "analysisRunPhase": "",
        "httpsHostname": environment["hostname"],
        "readyPodCount": 0,
        "observedImageIds": [],
        "checks": [],
    }
    if args.runtime_facts:
        facts = json.loads(args.runtime_facts.read_text())
        if not isinstance(facts, dict):
            raise SystemExit("Runtime facts must be a JSON object.")
        unknown = set(facts) - set(runtime)
        if unknown:
            raise SystemExit(f"Runtime facts contain unknown fields: {sorted(unknown)}")
        runtime.update(facts)

    if args.status == "qualified":
        if runtime["argoRevision"] != args.control_plane_sha:
            raise SystemExit("Qualified Argo revision must equal protected main.")
        if runtime["readyPodCount"] < 1 or not runtime["observedImageIds"]:
            raise SystemExit("Qualified runtime facts require ready Pods and image IDs.")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    result = {
        "schemaVersion": "v0.10.3",
        "application": "demo-api",
        "environment": args.environment,
        "releaseId": args.release_id,
        "status": args.status,
        "reason": args.reason,
        "recordedAt": now.isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "controlPlane": {
            "repository": "SterlingAureum/startup-devops-baseline",
            "ref": "refs/heads/main",
            "revision": args.control_plane_sha,
            "releaseFile": expected_release_file,
            "releaseFileSha256": args.expected_release_file_sha256,
        },
        "expected": {
            "sourceCommit": args.expected_source_commit,
            "imageDigest": args.expected_image_digest,
            "imageReference": f"{repository}@{args.expected_image_digest}",
        },
        "executor": {
            "kind": "ephemeral-self-hosted",
            "githubEnvironment": environment["github_environment"],
            "runnerName": args.runner_name,
            "workflowRunId": args.workflow_run_id,
            "workflowRunAttempt": args.workflow_run_attempt,
            "awsCallerArn": args.aws_caller_arn,
            "clusterName": environment["cluster"],
        },
        "runtime": runtime,
    }
    reject_sensitive_keys(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
