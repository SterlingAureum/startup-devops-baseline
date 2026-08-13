#!/usr/bin/env python3
"""Deterministically hash the deployment inputs qualified for dev or test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CONTRACT_PATHS = {
    "aws-dev": Path("delivery/contracts/demo-api-qualification-scope.json"),
    "aws-test": Path("delivery/contracts/demo-api-qualification-scope-aws-test.json"),
}
PREFIX = b"demo-api-qualification-scope-v1\0"


def fail(message: str) -> None:
    raise SystemExit(message)


def calculate(root: Path, environment: str = "aws-dev") -> dict[str, Any]:
    root = root.resolve()
    if environment not in CONTRACT_PATHS:
        fail(f"Unsupported qualification scope environment: {environment}")
    contract_path_relative = CONTRACT_PATHS[environment]
    contract_path = root / contract_path_relative
    if not contract_path.is_file():
        fail(f"Missing qualification scope contract: {contract_path_relative}")
    contract_bytes = contract_path.read_bytes()
    try:
        contract = json.loads(contract_bytes)
    except json.JSONDecodeError as exc:
        fail(f"Invalid qualification scope contract: {exc}")
    if contract != {
        "schemaVersion": "v0.10.5",
        "application": "demo-api",
        "environment": environment,
        "algorithm": "sha256-path-content-v1",
        "include": contract.get("include"),
    }:
        fail("Qualification scope contract contains unknown or invalid fields.")
    patterns = contract.get("include")
    if not isinstance(patterns, list) or not patterns or not all(
        isinstance(item, str) and item and not item.startswith("/") for item in patterns
    ):
        fail("Qualification scope include patterns are invalid.")

    selected: dict[str, Path] = {}
    for pattern in patterns:
        matches = [path for path in root.glob(pattern) if path.is_file()]
        if not matches:
            fail(f"Qualification scope pattern matched no files: {pattern}")
        for path in matches:
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                fail(f"Qualification scope escaped the repository: {path}")
            if path.is_symlink():
                fail(f"Qualification scope may not contain symlinks: {relative}")
            selected[relative.as_posix()] = resolved

    digest = hashlib.sha256(PREFIX)
    files = []
    for relative in sorted(selected):
        content_sha = hashlib.sha256(selected[relative].read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_sha.encode("ascii"))
        digest.update(b"\n")
        files.append({"path": relative, "sha256": content_sha})

    return {
        "schemaVersion": "v0.10.5",
        "application": "demo-api",
        "environment": environment,
        "algorithm": "sha256-path-content-v1",
        "contract": contract_path_relative.as_posix(),
        "contractSha256": hashlib.sha256(contract_bytes).hexdigest(),
        "scopeSha256": digest.hexdigest(),
        "files": files,
    }
