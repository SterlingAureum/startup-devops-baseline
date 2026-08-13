#!/usr/bin/env python3
"""Reject a release-only PR when a newer aws-dev Release is already active."""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from typing import Any


_collector_path = Path(__file__).resolve().parent / "collect-demo-api-orchestration-snapshot.py"
_collector_spec = importlib.util.spec_from_file_location("demo_api_snapshot_collector", _collector_path)
if _collector_spec is None or _collector_spec.loader is None:
    raise RuntimeError("Could not load orchestration snapshot collector")
_collector = importlib.util.module_from_spec(_collector_spec)
_collector_spec.loader.exec_module(_collector)
parse_release_text = _collector.parse_release_text


RELEASE_PATH = re.compile(r"^apps/demo-api/helm/values/releases/(aws-dev|aws-test|aws-prod)\.yaml$")


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
    return RELEASE_PATH.fullmatch(path).group(1), parse_release_text(text, f"PR #{pr['number']}:{path}")


def relation(root: Path, selected: dict[str, str], candidate: dict[str, str]) -> str:
    if selected["releaseId"] == candidate["releaseId"]:
        return "same"
    if selected["sourceCommit"] == candidate["sourceCommit"]:
        selected_run = int(selected["buildWorkflowRunId"])
        candidate_run = int(candidate["buildWorkflowRunId"])
        return "newer" if candidate_run > selected_run else "older"
    forward = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", selected["sourceCommit"], candidate["sourceCommit"]],
        check=False,
    ).returncode == 0
    backward = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", candidate["sourceCommit"], selected["sourceCommit"]],
        check=False,
    ).returncode == 0
    if forward:
        return "newer"
    if backward:
        return "older"
    return "ambiguous"


def validate_currentness(
    root: Path,
    repository: str,
    current_number: int,
    current_pr: dict[str, Any],
    open_prs: list[dict[str, Any]],
) -> str:
    selected = relevant(current_pr, repository)
    if selected is None:
        return "not-a-release-pr"
    target, selected_identity = selected
    main_path = root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
    active = parse_release_text(main_path.read_text(), str(main_path.relative_to(root)))
    candidates = [("current main aws-dev", active)]
    for pr in open_prs:
        if int(pr["number"]) == current_number:
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
    if args.current_pr_json:
        current = json.loads(args.current_pr_json.read_text())
    else:
        current = run_json(["gh", "pr", "view", str(args.pr_number), "--json", "number,headRefOid,files"])
    if args.open_prs_json:
        open_prs = json.loads(args.open_prs_json.read_text())
    else:
        summaries = run_json(["gh", "pr", "list", "--state", "open", "--base", "main", "--limit", "100", "--json", "number,headRefOid"])
        open_prs = [
            run_json(["gh", "pr", "view", str(item["number"]), "--json", "number,headRefOid,files"])
            for item in summaries
        ]
    result = validate_currentness(args.root.resolve(), args.repository, args.pr_number, current, open_prs)
    print(f"demo-api release PR currentness validation passed: {result}")


if __name__ == "__main__":
    main()
