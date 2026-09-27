#!/usr/bin/env python3
"""Validate the reviewed v0.11 historical snapshot and its orchestration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


SNAPSHOT_COMMIT = "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7"
MANIFEST = "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
LATEST = "validate-v0.12.3.2-post-promotion-historical-snapshot.sh"
PREDECESSOR = "validate-v0.12.3.1.1-release-change-routing-repair.sh"
ENTRYPOINT_RE = re.compile(r"validate-v0\.11[0-9A-Za-z._-]*\.sh")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
CURRENT_V011_CALL_RE = re.compile(
    r'^\s*(?:bash\s+)?["\']?\$\{ROOT_DIR\}/scripts/'
    r'(validate-v0\.11[0-9A-Za-z._-]*\.sh)["\']?\s*$',
    re.MULTILINE,
)
SNAPSHOT_V011_CALL_RE = re.compile(
    r'^\s*(?:bash\s+)?["\']?\$\{V011_HISTORICAL_SNAPSHOT_ROOT\}/scripts/'
    r'(validate-v0\.11[0-9A-Za-z._-]*\.sh)["\']?\s*$',
    re.MULTILINE,
)
TRANSITIVE_V011_BRIDGES = {
    "validate-v0.12.0-production-readiness-foundation.sh":
        "validate-v0.11.9.3.6.7.7.20.1-roadmap-status-successor-repair.sh",
    "validate-v0.12.1.0.1-ci-compatibility-repair.sh":
        "validate-v0.11.9.3.6.7.6-guarded-aws-test-teardown.sh",
}


class SnapshotError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def git(root: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
    )
    if check:
        require(result.returncode == 0, f"git command failed: {' '.join(arguments)}")
    return result.stdout.strip()


def manifest_entries(root: Path) -> list[str]:
    path = root / MANIFEST
    require(path.is_file() and not path.is_symlink(), "snapshot manifest missing")
    entries = path.read_text().splitlines()
    require(len(entries) == 112, "snapshot entrypoint count drift")
    require(len(entries) == len(set(entries)), "duplicate snapshot entrypoint")
    require(all(ENTRYPOINT_RE.fullmatch(item) for item in entries), "invalid snapshot entrypoint")
    return entries


def verify_snapshot(current_root: Path, snapshot_root: Path, expected_commit: str) -> dict[str, object]:
    current_root = current_root.resolve()
    snapshot_root = snapshot_root.resolve()
    require(current_root != snapshot_root, "snapshot must be isolated")
    require(COMMIT_RE.fullmatch(expected_commit) is not None, "invalid snapshot commit")
    require(git(snapshot_root, "rev-parse", "HEAD") == expected_commit, "snapshot HEAD drift")
    require(git(snapshot_root, "status", "--porcelain") == "", "snapshot worktree dirty")
    ancestor = subprocess.run(
        ["git", "-C", str(current_root), "merge-base", "--is-ancestor", expected_commit, "HEAD"],
        capture_output=True,
    )
    require(ancestor.returncode == 0, "snapshot is not an ancestor of current HEAD")
    current_manifest = current_root / MANIFEST
    snapshot_manifest = snapshot_root / MANIFEST
    require(current_manifest.is_file() and not current_manifest.is_symlink(), "current manifest missing")
    require(current_manifest.read_bytes() == snapshot_manifest.read_bytes(), "snapshot manifest drift")
    entries = manifest_entries(snapshot_root)
    indexed_modes: dict[str, str] = {}
    for line in git(snapshot_root, "ls-files", "-s", "--", "scripts").splitlines():
        metadata, indexed_path = line.split("\t", 1)
        mode, _object_id, stage = metadata.split()
        require(stage == "0" and indexed_path not in indexed_modes, "snapshot index drift")
        indexed_modes[indexed_path] = mode
    for name in entries:
        path = snapshot_root / "scripts" / name
        relative = f"scripts/{name}"
        require(path.is_file() and not path.is_symlink(), f"snapshot validator missing: {name}")
        require(indexed_modes.get(relative) == "100755", f"snapshot validator mode drift: {name}")
        require(os.access(path, os.X_OK), f"snapshot validator is not executable: {name}")
    return {
        "status": "historical-snapshot-verified",
        "snapshotCommit": expected_commit,
        "entrypointCount": len(entries),
        "snapshotClean": True,
        "snapshotAncestor": True,
        "manifestMatchesCurrent": True,
    }


def validate_repository(root: Path) -> dict[str, object]:
    root = root.resolve()
    root_gate = (root / "scripts/validate-ci-quality-gates.sh").read_text()
    validator = (root / "scripts" / LATEST).read_text()
    history = (root / "scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh").read_text()
    topology_241 = (root / "scripts/check-v0.12.2.4.1-validator-orchestration.py").read_text()
    topology_242 = (root / "scripts/check-v0.12.2.4.2-quality-gate-orchestration.py").read_text()
    predecessor = (root / "scripts/check-v0.12.3.1.1-release-change-routing-repair.py").read_text()
    workflow = (root / ".github/workflows/reusable-quality-gates.yaml").read_text()

    active_root = root_gate.split(": <<'V012242_PRE_CORE_LEGACY_REGISTRATION'", 1)[0]
    require(f'"${{ROOT_DIR}}/scripts/{LATEST}"' in active_root, "latest snapshot validator is not root")
    require(f'"${{ROOT_DIR}}/scripts/{PREDECESSOR}"' not in active_root, "predecessor remains root")
    for marker in (
        f'SNAPSHOT_COMMIT="{SNAPSHOT_COMMIT}"',
        'git -C "${ROOT_DIR}" merge-base --is-ancestor',
        'git -C "${ROOT_DIR}" worktree add --detach',
        "V011_HISTORICAL_SNAPSHOT_ROOT",
        "V011_HISTORICAL_SNAPSHOT_COMMIT",
    ):
        require(marker in validator, f"snapshot validator boundary missing: {marker}")
    for marker in (
        'v011_validation_root="${V011_HISTORICAL_SNAPSHOT_ROOT:-${ROOT_DIR}}"',
        'V011_HISTORICAL_SNAPSHOT_COMMIT',
        'bash "${v011_validation_root}/scripts/${validator}"',
    ):
        require(marker in history, f"historical delegation boundary missing: {marker}")
    require(f'"{LATEST}": PREDECESSOR' in topology_241, "v0.12.2.4.1 is not successor-aware")
    require(f'"{LATEST}": PREDECESSOR_ORCHESTRATOR' in topology_242, "v0.12.2.4.2 is not successor-aware")
    require(LATEST in predecessor, "release repair checker is not successor-aware")
    require("fetch-depth: 0" in workflow, "full Git history checkout removed")

    observed_bridges: dict[str, str] = {}
    for path in sorted((root / "scripts").glob("validate-v0.12*.sh")):
        text = path.read_text()
        current_calls = CURRENT_V011_CALL_RE.findall(text)
        snapshot_calls = SNAPSHOT_V011_CALL_RE.findall(text)
        if not current_calls and not snapshot_calls:
            continue
        require(len(current_calls) == 1, f"ambiguous current v0.11 bridge: {path.name}")
        require(len(snapshot_calls) == 1, f"ambiguous snapshot v0.11 bridge: {path.name}")
        require(current_calls == snapshot_calls, f"v0.11 bridge target drift: {path.name}")
        require(
            'if [[ -n "${V011_HISTORICAL_SNAPSHOT_ROOT:-}" ]]' in text,
            f"snapshot branch missing: {path.name}",
        )
        for marker in (
            '"${V011_HISTORICAL_SNAPSHOT_ROOT}" != "${ROOT_DIR}"',
            f'"${{V011_HISTORICAL_SNAPSHOT_COMMIT:-}}" == "{SNAPSHOT_COMMIT}"',
            'git -C "${V011_HISTORICAL_SNAPSHOT_ROOT}" rev-parse HEAD',
            'git -C "${V011_HISTORICAL_SNAPSHOT_ROOT}" status --porcelain',
            'Historical v0.11 snapshot commit was supplied without an isolated root.',
        ):
            require(marker in text, f"transitive snapshot boundary missing: {path.name}: {marker}")
        observed_bridges[path.name] = current_calls[0]
    require(observed_bridges == TRANSITIVE_V011_BRIDGES, "transitive v0.11 bridge inventory drift")
    return {
        "status": "post-promotion-historical-snapshot-validated",
        "snapshotCommit": SNAPSHOT_COMMIT,
        "transitiveV011BridgeCount": len(observed_bridges),
        "v011EntrypointCount": 112,
        "currentV012ValidationPreserved": True,
        "requiredCheckPreserved": True,
        "workflowTriggersPreserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify-snapshot-root", type=Path)
    parser.add_argument("--snapshot-commit", default=SNAPSHOT_COMMIT)
    args = parser.parse_args()
    if args.verify_snapshot_root:
        require(args.snapshot_commit == SNAPSHOT_COMMIT, "snapshot commit override prohibited")
        report = verify_snapshot(args.root, args.verify_snapshot_root, args.snapshot_commit)
    else:
        report = validate_repository(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
