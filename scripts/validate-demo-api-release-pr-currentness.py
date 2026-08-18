#!/usr/bin/env python3
"""Validate ordinary Promotion currentness or a governed historical rollback PR."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


_collector_path = Path(__file__).resolve().parent / "collect-demo-api-orchestration-snapshot.py"
_collector_spec = importlib.util.spec_from_file_location("demo_api_snapshot_collector", _collector_path)
if _collector_spec is None or _collector_spec.loader is None:
    raise RuntimeError("Could not load orchestration snapshot collector")
_collector = importlib.util.module_from_spec(_collector_spec)
_collector_spec.loader.exec_module(_collector)
parse_release_text = _collector.parse_release_text


RELEASE_PATH = re.compile(r"^apps/demo-api/helm/values/releases/(aws-dev|aws-test|aws-prod)\.yaml$")
ROLLBACK_BRANCH = re.compile(
    r"^rollback/demo-api-(aws-dev|aws-test|aws-prod)-([1-9][0-9]*)-([1-9][0-9]*)$"
)
RELEASE_ID = re.compile(r"^demo-api-[0-9a-f]{12}-[0-9a-f]{12}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
RUN_ID = re.compile(r"^[1-9][0-9]*$")


def fail(message: str) -> None:
    raise SystemExit(message)


def run_json(command: list[str]) -> Any:
    result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        fail(result.stderr.strip() or f"Command failed: {' '.join(command)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Command returned invalid JSON: {exc}")


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def git_success(root: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def content(repository: str, path: str, ref: str) -> str:
    response = run_json(["gh", "api", "--method", "GET", f"repos/{repository}/contents/{path}", "-f", f"ref={ref}"])
    if response.get("encoding") != "base64":
        fail(f"GitHub did not return file content for {path}@{ref}")
    return base64.b64decode(response["content"]).decode()


def relevant(pr: dict[str, Any], repository: str) -> tuple[str, dict[str, str]] | None:
    files = pr.get("files", [])
    matches = [item for item in files if RELEASE_PATH.fullmatch(item.get("path", ""))]
    if not matches:
        return None
    if len(files) != 1 or len(matches) != 1:
        fail(f"PR #{pr['number']} changes a release file plus unrelated paths")
    item = matches[0]
    path = item["path"]
    text = item.get("content")
    if text is None:
        text = content(repository, path, pr["headRefOid"])
    match = RELEASE_PATH.fullmatch(path)
    if match is None:
        raise AssertionError("release path match disappeared")
    return match.group(1), parse_release_text(text, f"PR #{pr['number']}:{path}")


def relation(root: Path, selected: dict[str, str], candidate: dict[str, str]) -> str:
    if selected["releaseId"] == candidate["releaseId"]:
        return "same"
    if selected["sourceCommit"] == candidate["sourceCommit"]:
        selected_run = int(selected["buildWorkflowRunId"])
        candidate_run = int(candidate["buildWorkflowRunId"])
        return "newer" if candidate_run > selected_run else "older"
    forward = git_success(root, "merge-base", "--is-ancestor", selected["sourceCommit"], candidate["sourceCommit"])
    backward = git_success(root, "merge-base", "--is-ancestor", candidate["sourceCommit"], selected["sourceCommit"])
    if forward:
        return "newer"
    if backward:
        return "older"
    return "ambiguous"


def body_value(body: str, label: str) -> str:
    matches = re.findall(rf"^- {re.escape(label)}: `([^`]+)`$", body, flags=re.MULTILINE)
    if len(matches) != 1:
        fail(f"Governed rollback PR must contain exactly one machine-readable '{label}' field")
    return matches[0]


def verify_rollback_workflow_run(
    repository: str,
    run_id: int,
    run_attempt: int,
    captured_main: str,
    lookup: Callable[[int], dict[str, Any]],
) -> None:
    run = lookup(run_id)
    if int(run.get("id", 0)) != run_id:
        fail("Rollback provenance workflow run ID mismatch")
    if run.get("event") != "workflow_dispatch":
        fail("Rollback provenance is not a manual workflow_dispatch run")
    if run.get("head_branch") != "main" or run.get("head_sha") != captured_main:
        fail("Rollback provenance is not bound to the captured protected main revision")
    if int(run.get("run_attempt", 0)) != run_attempt:
        fail("Rollback provenance workflow run attempt mismatch")
    path = str(run.get("path", "")).split("@", 1)[0]
    if path != ".github/workflows/demo-api-rollback.yaml":
        fail("Rollback provenance points to an unexpected workflow")
    if run.get("status") not in {"queued", "in_progress", "completed"}:
        fail("Rollback provenance workflow has an invalid status")
    if run.get("status") == "completed" and run.get("conclusion") != "success":
        fail("Rollback provenance workflow did not complete successfully")
    run_repository = run.get("repository", {})
    if run_repository and run_repository.get("full_name") != repository:
        fail("Rollback provenance belongs to another repository")


def validate_governed_rollback(
    root: Path,
    repository: str,
    pr: dict[str, Any],
    target: str,
    selected_identity: dict[str, str],
    run_lookup: Callable[[int], dict[str, Any]],
) -> str:
    branch = str(pr.get("headRefName", ""))
    branch_match = ROLLBACK_BRANCH.fullmatch(branch)
    if branch_match is None:
        fail("Governed rollback branch identity is invalid")
    branch_environment, raw_run_id, raw_run_attempt = branch_match.groups()
    if branch_environment != target:
        fail("Rollback branch environment differs from the changed release file")
    if pr.get("baseRefName") != "main":
        fail("Governed rollback PR must target main")

    body = str(pr.get("body", ""))
    schema = body_value(body, "Rollback metadata schema")
    body_environment = body_value(body, "Target environment")
    target_revision = body_value(body, "Historical desired-state commit")
    expected_current_release = body_value(body, "Expected current Release ID")
    restored_tag = body_value(body, "Restored image tag")
    restored_digest = body_value(body, "Restored image digest")
    restored_source = body_value(body, "Restored source commit")
    captured_main = body_value(body, "Captured main revision")
    body_run_id = body_value(body, "Workflow run ID")
    body_run_attempt = body_value(body, "Workflow run attempt")

    if schema != "v0.10.8.3":
        fail("Unsupported governed rollback PR metadata schema")
    if body_environment != target:
        fail("Rollback PR metadata environment differs from the changed release file")
    if SHA.fullmatch(target_revision) is None or SHA.fullmatch(captured_main) is None:
        fail("Rollback PR metadata contains an invalid Git revision")
    if RELEASE_ID.fullmatch(expected_current_release) is None:
        fail("Rollback PR metadata lacks a valid expected current Release ID")
    if RUN_ID.fullmatch(body_run_id) is None or RUN_ID.fullmatch(body_run_attempt) is None:
        fail("Rollback PR metadata contains an invalid workflow identity")

    run_id = int(raw_run_id)
    run_attempt = int(raw_run_attempt)
    if int(body_run_id) != run_id or int(body_run_attempt) != run_attempt:
        fail("Rollback branch and PR metadata workflow identities differ")

    head = git_output(root, "rev-parse", "HEAD")
    if head != captured_main:
        fail("Protected main advanced after rollback preparation; rerun the rollback workflow")
    if not git_success(root, "cat-file", "-e", f"{target_revision}^{{commit}}"):
        fail("Historical rollback commit is unavailable")
    if not git_success(root, "merge-base", "--is-ancestor", target_revision, captured_main):
        fail("Historical rollback commit is not contained in captured main")

    path = f"apps/demo-api/helm/values/releases/{target}.yaml"
    parent = git_output(root, "rev-parse", f"{target_revision}^1")
    changed = [item for item in git_output(root, "diff", "--name-only", parent, target_revision).splitlines() if item]
    if changed != [path]:
        fail(f"Historical rollback commit must change only {path}")
    historical_text = git_output(root, "show", f"{target_revision}:{path}") + "\n"
    historical_identity = parse_release_text(historical_text, f"{path}@{target_revision}")
    if historical_identity != selected_identity:
        fail("Rollback PR release identity differs from the declared historical commit")

    current_path = root / path
    current_identity = parse_release_text(current_path.read_text(), str(current_path.relative_to(root)))
    if current_identity["releaseId"] != expected_current_release:
        fail("Target environment no longer carries the expected current Release ID")
    if relation(root, selected_identity, current_identity) != "newer":
        fail("Governed rollback target is not an older unambiguous Release")

    if restored_tag != selected_identity["imageTag"]:
        fail("Rollback PR metadata image tag differs from the historical Release")
    if restored_digest != selected_identity["imageDigest"]:
        fail("Rollback PR metadata image digest differs from the historical Release")
    if restored_source != selected_identity["sourceCommit"]:
        fail("Rollback PR metadata source commit differs from the historical Release")
    expected_title = f"release: roll back demo-api {target} to {selected_identity['imageTag']}"
    if pr.get("title") != expected_title:
        fail("Rollback PR title differs from the governed workflow format")

    verify_rollback_workflow_run(repository, run_id, run_attempt, captured_main, run_lookup)
    return "governed-rollback"


def validate_currentness(
    root: Path,
    repository: str,
    current_number: int,
    current_pr: dict[str, Any],
    open_prs: list[dict[str, Any]],
    run_lookup: Callable[[int], dict[str, Any]] | None = None,
) -> str:
    selected = relevant(current_pr, repository)
    if selected is None:
        return "not-a-release-pr"
    target, selected_identity = selected

    if ROLLBACK_BRANCH.fullmatch(str(current_pr.get("headRefName", ""))):
        if run_lookup is None:
            run_lookup = lambda run_id: run_json(
                ["gh", "api", "--method", "GET", f"repos/{repository}/actions/runs/{run_id}"]
            )
        return validate_governed_rollback(
            root, repository, current_pr, target, selected_identity, run_lookup
        )

    main_path = root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
    active = parse_release_text(main_path.read_text(), str(main_path.relative_to(root)))
    candidates = [("current main aws-dev", active)]
    for pr in open_prs:
        if int(pr["number"]) == current_number:
            continue
        if ROLLBACK_BRANCH.fullmatch(str(pr.get("headRefName", ""))):
            continue
        value = relevant(pr, repository)
        if value and value[0] == "aws-dev":
            candidates.append((f"open aws-dev PR #{pr['number']}", value[1]))
    for label, candidate in candidates:
        order = relation(root, selected_identity, candidate)
        if order == "newer":
            fail(
                f"Release PR is superseded by {label}: "
                f"{candidate['releaseId']} is newer than {selected_identity['releaseId']}"
            )
        if order == "ambiguous":
            fail(f"Release order is ambiguous relative to {label}; manual review is required")
    if target in {"aws-test", "aws-prod"} and selected_identity["releaseId"] != active["releaseId"]:
        fail(f"{target} PR no longer matches the current main aws-dev Release")
    return "current"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--current-pr-json", type=Path)
    parser.add_argument("--open-prs-json", type=Path)
    args = parser.parse_args()
    fields = "number,headRefOid,headRefName,baseRefName,title,body,files"
    if args.current_pr_json:
        current = json.loads(args.current_pr_json.read_text())
    else:
        current = run_json(["gh", "pr", "view", str(args.pr_number), "--json", fields])
    if args.open_prs_json:
        open_prs = json.loads(args.open_prs_json.read_text())
    else:
        summaries = run_json(
            ["gh", "pr", "list", "--state", "open", "--base", "main", "--limit", "100", "--json", "number"]
        )
        open_prs = [
            run_json(["gh", "pr", "view", str(item["number"]), "--json", fields])
            for item in summaries
        ]
    result = validate_currentness(args.root.resolve(), args.repository, args.pr_number, current, open_prs)
    print(f"demo-api release PR currentness validation passed: {result}")


if __name__ == "__main__":
    main()
