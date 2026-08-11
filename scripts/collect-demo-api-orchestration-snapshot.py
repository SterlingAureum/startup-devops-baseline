#!/usr/bin/env python3
"""Collect read-only Git and GitHub facts for the demo-api orchestrator."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ENVIRONMENTS = ("aws-dev", "aws-test", "aws-prod")
STATIC_MAX_AGE = 604800
RUNTIME_MAX_AGE = 259200
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID_PATTERN = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")


def fail(message: str) -> None:
    raise SystemExit(message)


def scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def parse_release_text(text: str, label: str) -> dict[str, str]:
    values: dict[tuple[str, str], str] = {}
    section: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            continue
        if indent == 2 and section and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            field = (section, key)
            if field in values:
                fail(f"{label}:{number}: duplicate {section}.{key}")
            values[field] = scalar(raw_value)
            continue
        fail(f"{label}:{number}: unsupported release values structure")

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
        fail(f"{label}: release values do not satisfy the isolated schema")

    source_commit = values[("delivery", "sourceCommit")]
    digest = values[("image", "digest")]
    tag = values[("image", "tag")]
    if not SHA_PATTERN.fullmatch(source_commit):
        fail(f"{label}: invalid source commit")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail(f"{label}: invalid image digest")
    if tag != f"sha-{source_commit[:7]}":
        fail(f"{label}: image tag differs from source commit")
    if values[("release", "applicationVersion")] != tag:
        fail(f"{label}: applicationVersion differs from image tag")
    workflow_run_id = values[("delivery", "workflowRunId")]
    if not re.fullmatch(r"[0-9]+", workflow_run_id):
        fail(f"{label}: invalid build workflow run ID")

    release_id = f"demo-api-{source_commit[:12]}-{digest.removeprefix('sha256:')[:12]}"
    return {
        "releaseId": release_id,
        "sourceRepository": values[("delivery", "sourceRepository")],
        "sourceCommit": source_commit,
        "imageRepository": values[("image", "repository")],
        "imageTag": tag,
        "imageDigest": digest,
        "buildWorkflowRunId": workflow_run_id,
    }


def release_fact(root: Path, environment: str) -> dict[str, Any]:
    relative = Path(f"apps/demo-api/helm/values/releases/{environment}.yaml")
    path = root / relative
    if not path.is_file():
        fail(f"Missing release file: {relative}")
    content = path.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(content).hexdigest(),
        "identity": parse_release_text(content.decode(), str(relative)),
    }


def run_json(command: list[str]) -> Any:
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        fail(f"Required command not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        fail(f"Command failed: {' '.join(command)}\n{exc.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Command did not return JSON: {' '.join(command)}: {exc}")


def github_file(repository: str, path: str, ref: str) -> str:
    response = run_json(
        [
            "gh",
            "api",
            "--method",
            "GET",
            f"repos/{repository}/contents/{path}",
            "-f",
            f"ref={ref}",
        ]
    )
    if response.get("encoding") != "base64" or not isinstance(response.get("content"), str):
        fail(f"GitHub did not return base64 content for {path}@{ref}")
    return base64.b64decode(response["content"]).decode()


def load_open_prs(repository: str, fixture: Path | None) -> list[dict[str, Any]]:
    if fixture:
        data = json.loads(fixture.read_text())
        if not isinstance(data, list):
            fail("Open-PR fixture must contain a JSON array")
        return data

    prs = run_json(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--base",
            "main",
            "--limit",
            "100",
            "--json",
            "number,url,title,headRefName,headRefOid,baseRefName",
        ]
    )
    enriched = []
    for pr in prs:
        details = run_json(["gh", "pr", "view", str(pr["number"]), "--json", "files"])
        files = []
        for item in details.get("files", []):
            path = item.get("path", "")
            if re.fullmatch(r"apps/demo-api/helm/values/releases/aws-(dev|test|prod)\.yaml", path) or re.fullmatch(
                r"evidence/demo-api/(?:runtime/)?aws-(dev|test)/[^/]+\.json", path
            ):
                files.append(
                    {
                        "path": path,
                        "content": github_file(repository, path, pr["headRefOid"]),
                    }
                )
        enriched.append({**pr, "files": files, "totalFiles": len(details.get("files", []))})
    return enriched


def identity_from_evidence(text: str, label: str) -> dict[str, str]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"{label}: invalid evidence JSON: {exc}")
    release = document.get("release", {})
    source_commit = release.get("sourceCommit", "")
    digest = release.get("imageDigest", "")
    if not SHA_PATTERN.fullmatch(source_commit) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail(f"{label}: evidence does not carry a valid release identity")
    return {
        "releaseId": f"demo-api-{source_commit[:12]}-{digest.removeprefix('sha256:')[:12]}",
        "sourceRepository": release.get("sourceRepository", ""),
        "sourceCommit": source_commit,
        "imageRepository": release.get("imageRepository", ""),
        "imageTag": release.get("imageTag", ""),
        "imageDigest": digest,
        "buildWorkflowRunId": str(release.get("buildWorkflowRunId", "")),
    }


def classify_prs(raw_prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    classified = []
    for pr in raw_prs:
        files = pr.get("files", [])
        if pr.get("totalFiles", len(files)) != 1 or len(files) != 1:
            continue
        file = files[0]
        path = file.get("path", "")
        content = file.get("content", "")
        release_match = re.fullmatch(
            r"apps/demo-api/helm/values/releases/(aws-dev|aws-test|aws-prod)\.yaml",
            path,
        )
        static_match = re.fullmatch(r"evidence/demo-api/(aws-dev|aws-test)/[^/]+\.json", path)
        runtime_match = re.fullmatch(r"evidence/demo-api/runtime/(aws-dev|aws-test)/[^/]+\.json", path)
        if release_match:
            kind = "environment-release"
            environment = release_match.group(1)
            identity = parse_release_text(content, f"PR #{pr['number']}:{path}")
            release_sha256 = hashlib.sha256(content.encode()).hexdigest()
        elif static_match or runtime_match:
            kind = "runtime-evidence" if runtime_match else "static-evidence"
            environment = (runtime_match or static_match).group(1)
            identity = identity_from_evidence(content, f"PR #{pr['number']}:{path}")
            release_sha256 = json.loads(content)["release"]["sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", release_sha256):
                fail(f"PR #{pr['number']}:{path}: invalid source release SHA-256")
        else:
            continue
        classified.append(
            {
                "number": int(pr["number"]),
                "url": pr["url"],
                "kind": kind,
                "targetEnvironment": environment,
                "releaseId": identity["releaseId"],
                "releaseSha256": release_sha256,
                "headRefName": pr["headRefName"],
                "baseRefName": pr.get("baseRefName", "main"),
                "_identity": identity,
            }
        )
    return classified


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def empty_evidence() -> dict[str, Any]:
    return {"state": "missing", "id": None, "ref": None, "sha256": None}


def matching_evidence(
    root: Path,
    environment: str,
    identity: dict[str, str] | None,
    release_sha256: str,
    kind: str,
    now: datetime,
) -> dict[str, Any]:
    if identity is None:
        return empty_evidence()
    if kind == "static":
        directory = root / f"evidence/demo-api/{environment}"
        max_age = STATIC_MAX_AGE
        recorded_parent = "qualification"
        id_key = "workflowRunId"
    else:
        directory = root / f"evidence/demo-api/runtime/{environment}"
        max_age = RUNTIME_MAX_AGE
        recorded_parent = "runtime"
        id_key = "evidenceId"
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                document = json.loads(path.read_text())
                release = document["release"]
                recorded_at = parse_utc(document[recorded_parent]["recordedAt"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
            if (
                document.get("application") == "demo-api"
                and document.get("environment") == environment
                and document.get("status") == "passed"
                and release.get("sourceCommit") == identity["sourceCommit"]
                and release.get("imageDigest") == identity["imageDigest"]
                and release.get("sha256") == release_sha256
            ):
                candidates.append((recorded_at, path, document))
    if not candidates:
        return empty_evidence()
    recorded_at, path, document = max(candidates, key=lambda item: item[0])
    state = "fresh" if 0 <= (now - recorded_at).total_seconds() <= max_age else "stale"
    content = path.read_bytes()
    return {
        "state": state,
        "id": str(document[recorded_parent][id_key]),
        "ref": str(path.relative_to(root)),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def choose_active(
    operation: str,
    source_commit: str | None,
    requested_release_id: str | None,
    releases: dict[str, dict[str, Any]],
    prs: list[dict[str, Any]],
) -> dict[str, str] | None:
    candidates: dict[str, dict[str, str]] = {
        item["identity"]["releaseId"]: item["identity"] for item in releases.values()
    }
    for pr in prs:
        candidates[pr["_identity"]["releaseId"]] = pr["_identity"]
    if requested_release_id:
        if requested_release_id not in candidates:
            fail(f"Requested release ID was not found in main or an open PR: {requested_release_id}")
        return candidates[requested_release_id]
    if operation == "start" and source_commit:
        matching = [value for value in candidates.values() if value["sourceCommit"] == source_commit]
        if matching:
            return matching[-1]
        return None
    release_prs = [pr for pr in prs if pr["kind"] == "environment-release"]
    if release_prs:
        return max(release_prs, key=lambda item: item["number"])["_identity"]
    return releases["aws-dev"]["identity"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--operation", required=True, choices=("start", "status", "resume"))
    parser.add_argument("--policy", default="reviewed", choices=("reviewed", "continuous-nonprod"))
    parser.add_argument("--event-name", required=True, choices=("push", "workflow_dispatch", "fixture"))
    parser.add_argument("--ref", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--captured-main-revision", required=True)
    parser.add_argument("--observed-main-revision", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--requested-release-id")
    parser.add_argument("--open-prs-json", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    for label, value in (
        ("captured main revision", args.captured_main_revision),
        ("observed main revision", args.observed_main_revision),
    ):
        if not SHA_PATTERN.fullmatch(value):
            fail(f"Invalid {label}")
    if args.source_commit and not SHA_PATTERN.fullmatch(args.source_commit):
        fail("Invalid source commit")
    if args.requested_release_id and not RELEASE_ID_PATTERN.fullmatch(args.requested_release_id):
        fail("Invalid requested release ID")
    if args.ref != "refs/heads/main":
        fail("Orchestration facts may be collected only from protected main")

    root = Path(args.root).resolve()
    releases = {environment: release_fact(root, environment) for environment in ENVIRONMENTS}
    classified = classify_prs(load_open_prs(args.repository, args.open_prs_json))
    active = choose_active(
        args.operation,
        args.source_commit,
        args.requested_release_id,
        releases,
        classified,
    )
    now = parse_utc(args.now) if args.now else datetime.now(timezone.utc)

    evidence = {}
    for environment in ("aws-dev", "aws-test"):
        release_sha = releases[environment]["sha256"]
        evidence[environment] = {
            "static": matching_evidence(root, environment, active, release_sha, "static", now),
            "runtime": matching_evidence(root, environment, active, release_sha, "runtime", now),
        }

    public_prs = []
    for item in classified:
        public_prs.append({key: value for key, value in item.items() if not key.startswith("_")})

    snapshot = {
        "schemaVersion": "v0.10.2",
        "application": "demo-api",
        "operation": args.operation,
        "policy": args.policy,
        "trigger": {
            "eventName": args.event_name,
            "ref": args.ref,
            "sourceCommit": args.source_commit,
        },
        "capturedMainRevision": args.captured_main_revision,
        "observedMainRevision": args.observed_main_revision,
        "requestedReleaseId": args.requested_release_id,
        "activeRelease": active,
        "releases": releases,
        "evidence": evidence,
        "pullRequests": public_prs,
        "environmentAvailability": {environment: "unknown" for environment in ENVIRONMENTS},
        "derivedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"Collected read-only orchestration snapshot: {args.output}")


if __name__ == "__main__":
    main()
