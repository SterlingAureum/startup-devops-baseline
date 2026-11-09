#!/usr/bin/env python3
"""Validation helpers for the v0.10.5 dev/test qualification bundle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from demo_api_qualification_scope import calculate


SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
SENSITIVE_KEY = re.compile(
    r"(?:^|[-_])(secret|token|credential|password|kubeconfig)(?:$|[-_])",
    re.IGNORECASE,
)


def utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def reject_sensitive_keys(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require(not SENSITIVE_KEY.search(str(key)), f"Forbidden sensitive field: {path}.{key}")
            reject_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_keys(child, f"{path}[{index}]")


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def validate(
    document: dict[str, Any],
    root: Path | None = None,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> None:
    top = {
        "schemaVersion", "application", "environment", "releaseId", "status",
        "recordedAt", "expiresAt", "identity", "release", "qualificationScope",
        "staticQualification", "runtimeQualification", "orchestration",
    }
    require(set(document) == top, "Bundle has missing or unknown top-level fields.")
    require(document["schemaVersion"] == "v0.10.5", "Unsupported bundle schema.")
    require(document["application"] == "demo-api", "Unexpected application.")
    environment = document["environment"]
    require(environment in {"aws-dev", "aws-test"}, "Only aws-dev/aws-test bundles are implemented.")
    require(document["status"] == "qualified", "Bundle is not qualified.")
    require(RELEASE_ID.fullmatch(document["releaseId"]) is not None, "Invalid Release ID.")
    recorded_at = utc(document["recordedAt"])
    expires_at = utc(document["expiresAt"])
    require(recorded_at < expires_at, "Bundle expiry must follow recording time.")
    if require_fresh:
        observed_now = now or datetime.now(timezone.utc)
        require(recorded_at <= observed_now <= expires_at, "Qualification bundle is not currently fresh.")

    identity = document["identity"]
    require(set(identity) == {
        "sourceRepository", "sourceCommit", "imageRepository", "imageTag",
        "imageDigest", "buildWorkflowRunId",
    }, "Bundle identity is incomplete.")
    require(identity["sourceRepository"] == "SterlingAureum/startup-devops-baseline", "Unexpected source repository.")
    require(identity["imageRepository"] == "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api", "Unexpected image repository.")
    require(SHA.fullmatch(identity["sourceCommit"]) is not None, "Invalid source commit.")
    require(DIGEST.fullmatch(identity["imageDigest"]) is not None, "Invalid image digest.")
    require(identity["imageTag"] == f"sha-{identity['sourceCommit'][:7]}", "Image tag differs from source.")
    require(re.fullmatch(r"[1-9][0-9]*", str(identity["buildWorkflowRunId"])) is not None, "Invalid build run.")
    expected_release_id = (
        f"demo-api-{identity['sourceCommit'][:12]}-"
        f"{identity['imageDigest'].removeprefix('sha256:')[:12]}"
    )
    require(document["releaseId"] == expected_release_id, "Release ID differs from immutable identity.")

    release = document["release"]
    require(
        release.get("path") == f"apps/demo-api/helm/values/releases/{environment}.yaml",
        "Wrong release path.",
    )
    require(SHA256.fullmatch(release.get("sha256", "")) is not None, "Invalid release SHA-256.")

    static_wrapper = document["staticQualification"]
    runtime_wrapper = document["runtimeQualification"]
    require(set(static_wrapper) == {"sha256", "expiresAt", "result"}, "Invalid static wrapper.")
    require(set(runtime_wrapper) == {"sha256", "result"}, "Invalid runtime wrapper.")
    static = static_wrapper["result"]
    runtime = runtime_wrapper["result"]
    require(hashlib.sha256(canonical_bytes(static)).hexdigest() == static_wrapper["sha256"], "Static result hash mismatch.")
    require(hashlib.sha256(canonical_bytes(runtime)).hexdigest() == runtime_wrapper["sha256"], "Runtime result hash mismatch.")
    require(static.get("schemaVersion") == "v0.9.4" and static.get("status") == "passed", "Static qualification did not pass.")
    require(static.get("application") == "demo-api" and static.get("environment") == environment, "Static target mismatch.")
    require(runtime.get("schemaVersion") == "v0.10.3" and runtime.get("status") == "qualified", "Runtime qualification did not pass.")
    require(runtime.get("application") == "demo-api" and runtime.get("environment") == environment, "Runtime target mismatch.")
    require(runtime.get("releaseId") == document["releaseId"], "Runtime Release ID mismatch.")
    for field in ("sourceRepository", "sourceCommit", "imageRepository", "imageTag", "imageDigest", "buildWorkflowRunId"):
        require(str(static["release"].get(field, "")) == str(identity[field]), f"Static identity mismatch: {field}.")
    require(static["release"]["sha256"] == release["sha256"], "Static release hash mismatch.")
    require(runtime["controlPlane"]["releaseFileSha256"] == release["sha256"], "Runtime release hash mismatch.")
    require(runtime["expected"]["sourceCommit"] == identity["sourceCommit"], "Runtime source mismatch.")
    require(runtime["expected"]["imageDigest"] == identity["imageDigest"], "Runtime digest mismatch.")
    static_recorded = utc(static["qualification"]["recordedAt"])
    runtime_recorded = utc(runtime["recordedAt"])
    static_expires = utc(static_wrapper["expiresAt"])
    runtime_expires = utc(runtime["expiresAt"])
    require(static_recorded <= recorded_at and runtime_recorded <= recorded_at, "Bundle predates an input result.")
    require(static_recorded < static_expires and runtime_recorded < runtime_expires, "Input qualification expiry is invalid.")
    require(expires_at == min(static_expires, runtime_expires), "Bundle expiry is not the earliest input expiry.")

    orchestration = document["orchestration"]
    require(set(orchestration) == {
        "repository", "ref", "revision", "workflow", "workflowRunId",
        "workflowRunAttempt", "actor",
    }, "Invalid orchestration identity.")
    require(orchestration["repository"] == "SterlingAureum/startup-devops-baseline", "Unexpected repository.")
    require(orchestration["ref"] == "refs/heads/main", "Bundle was not produced from protected main.")
    require(SHA.fullmatch(orchestration["revision"]) is not None, "Invalid control-plane revision.")
    require(orchestration["workflow"] == ".github/workflows/demo-api-release-orchestrator.yaml", "Unexpected orchestrator workflow.")
    require(LOGIN.fullmatch(orchestration["actor"]) is not None, "Invalid actor.")
    for field in ("workflowRunId", "workflowRunAttempt"):
        require(re.fullmatch(r"[1-9][0-9]*", str(orchestration[field])) is not None, f"Invalid {field}.")
    require(str(static["qualification"]["workflowRunId"]) == str(orchestration["workflowRunId"]), "Static result came from another run.")
    require(str(static["qualification"]["workflowRunAttempt"]) == str(orchestration["workflowRunAttempt"]), "Static result came from another attempt.")
    require(str(runtime["executor"]["workflowRunId"]) == str(orchestration["workflowRunId"]), "Runtime result came from another run.")
    require(str(runtime["executor"]["workflowRunAttempt"]) == str(orchestration["workflowRunAttempt"]), "Runtime result came from another attempt.")
    require(static["qualification"]["repositoryRevision"] == orchestration["revision"], "Static control plane mismatch.")
    require(runtime["controlPlane"]["revision"] == orchestration["revision"], "Runtime control plane mismatch.")

    scope = document["qualificationScope"]
    require(set(scope) == {"algorithm", "contract", "contractSha256", "scopeSha256", "files"}, "Invalid scope record.")
    require(scope["algorithm"] == "sha256-path-content-v1", "Unsupported scope algorithm.")
    expected_contract = (
        "delivery/contracts/demo-api-qualification-scope.json"
        if environment == "aws-dev"
        else "delivery/contracts/demo-api-qualification-scope-aws-test.json"
    )
    require(scope["contract"] == expected_contract, "Unexpected scope contract.")
    require(SHA256.fullmatch(scope["contractSha256"]) is not None, "Invalid contract hash.")
    require(SHA256.fullmatch(scope["scopeSha256"]) is not None, "Invalid scope hash.")
    require(isinstance(scope["files"], list) and scope["files"], "Scope files are empty.")
    require(scope["files"] == sorted(scope["files"], key=lambda item: item["path"]), "Scope files are not sorted.")
    require(len({item["path"] for item in scope["files"]}) == len(scope["files"]), "Scope paths are duplicated.")
    if root is not None:
        current = calculate(root, environment)
        for field in ("algorithm", "contract", "contractSha256", "scopeSha256", "files"):
            require(scope[field] == current[field], f"Qualification scope is stale: {field}.")
        release_path = root / release["path"]
        require(hashlib.sha256(release_path.read_bytes()).hexdigest() == release["sha256"], "Current release differs from bundle.")

    reject_sensitive_keys(document)
