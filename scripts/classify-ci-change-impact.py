#!/usr/bin/env python3
"""Classify a Git change into a fail-closed CI quality-gate mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


SHA_RE = re.compile(r"[0-9a-f]{40}")
ZERO_SHA = "0" * 40
DOCUMENTATION_ROOT_FILES = {
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "README.md",
    "SECURITY.md",
}


def is_documentation_path(path: str) -> bool:
    return path.startswith("docs/") or path in DOCUMENTATION_ROOT_FILES


def is_validator_bound_documentation(root: Path, path: str) -> bool:
    try:
        for validator in (root / "scripts").glob("validate-*.sh"):
            if path in validator.read_text():
                return True
    except (OSError, UnicodeDecodeError):
        return True
    return False


def git_paths(root: Path, event: str, base: str, head: str) -> list[str]:
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        raise ValueError("invalid commit identity")
    if base == ZERO_SHA or head == ZERO_SHA or base == head:
        raise ValueError("ambiguous commit range")
    for revision in (base, head):
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{revision}^{{commit}}"],
            check=True,
            capture_output=True,
        )
    separator = "..." if event == "pull_request" else ".."
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            f"{base}{separator}{head}",
        ],
        check=True,
        capture_output=True,
    )
    paths = [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]
    if not paths:
        raise ValueError("empty change inventory")
    return paths


def classify(
    root: Path,
    requested_mode: str,
    event: str,
    base: str,
    head: str,
) -> dict[str, object]:
    if requested_mode == "full":
        return {
            "mode": "full",
            "reason": "explicit-full",
            "changedPathCount": 0,
            "documentationOnly": False,
        }
    if requested_mode == "image":
        return {
            "mode": "image",
            "reason": "explicit-demo-api-image",
            "changedPathCount": 0,
            "documentationOnly": False,
        }
    if requested_mode != "auto":
        return {
            "mode": "full",
            "reason": "unknown-requested-mode",
            "changedPathCount": 0,
            "documentationOnly": False,
        }
    if event not in {"pull_request", "push"}:
        return {
            "mode": "full",
            "reason": "non-diff-event",
            "changedPathCount": 0,
            "documentationOnly": False,
        }
    try:
        paths = git_paths(root, event, base, head)
    except (OSError, UnicodeDecodeError, ValueError, subprocess.CalledProcessError):
        return {
            "mode": "full",
            "reason": "unavailable-or-ambiguous-diff",
            "changedPathCount": 0,
            "documentationOnly": False,
        }
    documentation_candidate = all(is_documentation_path(path) for path in paths)
    contract_bound = documentation_candidate and any(
        is_validator_bound_documentation(root, path) for path in paths
    )
    documentation_only = documentation_candidate and not contract_bound
    return {
        "mode": "documentation" if documentation_only else "full",
        "reason": (
            "documentation-only"
            if documentation_only
            else "validator-bound-documentation"
            if contract_bound
            else "core-or-unknown-change"
        ),
        "changedPathCount": len(paths),
        "documentationOnly": documentation_only,
        "contractBoundDocumentation": contract_bound,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--requested-mode", default="full")
    parser.add_argument("--event", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--require-mode", choices=("full", "documentation", "image"))
    args = parser.parse_args()

    report = classify(
        args.root.resolve(), args.requested_mode, args.event, args.base, args.head
    )
    if args.require_mode and report["mode"] != args.require_mode:
        raise SystemExit(
            f"Expected CI mode {args.require_mode}, observed {report['mode']}: {report['reason']}"
        )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"mode={report['mode']}\n")
            output.write(f"reason={report['reason']}\n")
            output.write(f"changed-path-count={report['changedPathCount']}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
