#!/usr/bin/env python3
"""Resolve a read-only historical rollback candidate for a failed dev/test release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ELIGIBLE_REASONS = {
    "rollout_unhealthy", "analysis_failed", "digest_mismatch", "https_validation_failed",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RELEASE_ID = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")


def fail(message: str) -> None:
    raise SystemExit(message)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def scalar(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def identity(text: str, label: str) -> dict[str, str]:
    section = None
    values: dict[tuple[str, str], str] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
        elif indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            values[(section, key)] = scalar(value)
    source = values.get(("delivery", "sourceCommit"), "")
    digest = values.get(("image", "digest"), "")
    tag = values.get(("image", "tag"), "")
    repository = values.get(("image", "repository"), "")
    workflow_run = values.get(("delivery", "workflowRunId"), "")
    if not SHA.fullmatch(source) or not DIGEST.fullmatch(digest):
        fail(f"{label}: invalid immutable release identity")
    if tag != f"sha-{source[:7]}" or not re.fullmatch(r"[1-9][0-9]*", workflow_run):
        fail(f"{label}: inconsistent release metadata")
    return {
        "releaseId": f"demo-api-{source[:12]}-{digest.removeprefix('sha256:')[:12]}",
        "sourceCommit": source,
        "imageDigest": digest,
        "imageTag": tag,
        "imageRepository": repository,
        "buildWorkflowRunId": workflow_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--environment", required=True, choices=("aws-dev", "aws-test"))
    parser.add_argument("--failed-release-id", required=True)
    parser.add_argument("--failure-reason", required=True)
    parser.add_argument("--base-revision", default="HEAD")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    if RELEASE_ID.fullmatch(args.failed_release_id) is None:
        fail("Invalid failed Release ID.")
    if args.failure_reason not in ELIGIBLE_REASONS:
        fail("Failure reason is not eligible for a rollback handoff.")
    base = git(root, "rev-parse", "--verify", f"{args.base_revision}^{{commit}}").strip()
    if not SHA.fullmatch(base):
        fail("Invalid rollback base revision.")
    relative = f"apps/demo-api/helm/values/releases/{args.environment}.yaml"
    current_text = git(root, "show", f"{base}:{relative}")
    current = identity(current_text, f"{relative}@{base}")
    if current["releaseId"] != args.failed_release_id:
        fail("Current environment release is not the failed Release ID.")

    selected_revision = None
    selected = None
    for revision in git(root, "log", "--format=%H", base, "--", relative).splitlines():
        if not SHA.fullmatch(revision):
            continue
        try:
            candidate = identity(git(root, "show", f"{revision}:{relative}"), f"{relative}@{revision}")
        except SystemExit:
            continue
        if candidate["releaseId"] == current["releaseId"]:
            continue
        parent_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", f"{revision}^1"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if parent_result.returncode != 0:
            continue
        parent = parent_result.stdout.strip()
        changed = [line for line in git(root, "diff", "--name-only", parent, revision).splitlines() if line]
        if changed != [relative]:
            continue
        selected_revision = revision
        selected = candidate
        break
    if selected_revision is None or selected is None:
        fail("No exact historical target-release-only rollback candidate was found.")

    current_sha = hashlib.sha256(current_text.encode()).hexdigest()
    command = (
        "gh workflow run demo-api-rollback.yaml --ref main "
        f"-f target_environment={args.environment} "
        f"-f rollback_to_revision={selected_revision} "
        f"-f expected_current_release_id={args.failed_release_id}"
    )
    value = {
        "targetEnvironment": args.environment,
        "failedReleaseId": args.failed_release_id,
        "currentReleaseSha256": current_sha,
        "rollbackToRevision": selected_revision,
        "previousReleaseId": selected["releaseId"],
        "previousImageDigest": selected["imageDigest"],
        "failureReason": args.failure_reason,
        "manualWorkflowCommand": command,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(f"Resolved reviewed rollback handoff candidate: {selected_revision}")


if __name__ == "__main__":
    main()
