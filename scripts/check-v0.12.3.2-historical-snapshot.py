#!/usr/bin/env python3
"""Validate static historical attestation without replaying old validators."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


SNAPSHOT_COMMIT = "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7"
SNAPSHOT_RELEASE = "apps/demo-api/helm/values/releases/aws-dev.yaml"
SNAPSHOT_RELEASE_SHA256 = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
MANIFEST = "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
LATEST = "validate-v0.12.3.2-post-promotion-historical-snapshot.sh"
PREDECESSOR = "validate-v0.12.3.1.1-release-change-routing-repair.sh"
ENTRYPOINT_RE = re.compile(r"validate-v0\.11[0-9A-Za-z._-]*\.sh")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")


class SnapshotError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError(message)


def git(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=not binary,
    )
    require(result.returncode == 0, f"git command failed: {' '.join(arguments)}")
    if binary:
        return result.stdout
    return result.stdout.strip()


def manifest_entries(root: Path) -> list[str]:
    path = root / MANIFEST
    require(path.is_file() and not path.is_symlink(), "current manifest missing")
    entries = path.read_text().splitlines()
    require(len(entries) == 112, "snapshot entrypoint count drift")
    require(len(entries) == len(set(entries)), "duplicate snapshot entrypoint")
    require(all(ENTRYPOINT_RE.fullmatch(item) for item in entries), "invalid snapshot entrypoint")
    return entries


def verify_static_attestation(
    root: Path,
    expected_commit: str,
    *,
    expected_release_sha256: str = SNAPSHOT_RELEASE_SHA256,
) -> dict[str, object]:
    root = root.resolve()
    require(COMMIT_RE.fullmatch(expected_commit) is not None, "invalid snapshot commit")
    git(root, "cat-file", "-e", f"{expected_commit}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", expected_commit, "HEAD"],
        capture_output=True,
    )
    require(ancestor.returncode == 0, "snapshot is not an ancestor of current HEAD")

    entries = manifest_entries(root)
    snapshot_manifest_object = git(root, "rev-parse", f"{expected_commit}:{MANIFEST}")
    current_manifest_object = git(root, "hash-object", MANIFEST)
    require(snapshot_manifest_object == current_manifest_object, "snapshot manifest drift")

    indexed_modes: dict[str, tuple[str, str]] = {}
    tree = git(root, "ls-tree", "-r", "--full-tree", expected_commit, "--", "scripts")
    assert isinstance(tree, str)
    for line in tree.splitlines():
        metadata, indexed_path = line.split("\t", 1)
        mode, object_type, _object_id = metadata.split()
        require(indexed_path not in indexed_modes, "snapshot tree entry duplicated")
        indexed_modes[indexed_path] = (mode, object_type)
    for name in entries:
        relative = f"scripts/{name}"
        require(
            indexed_modes.get(relative) == ("100755", "blob"),
            f"snapshot validator mode drift: {name}",
        )

    release = git(root, "show", f"{expected_commit}:{SNAPSHOT_RELEASE}", binary=True)
    assert isinstance(release, bytes)
    release_sha256 = hashlib.sha256(release).hexdigest()
    require(release_sha256 == expected_release_sha256, "snapshot release digest drift")
    return {
        "status": "historical-snapshot-statically-attested",
        "snapshotCommit": expected_commit,
        "snapshotAncestor": True,
        "manifestMatchesCurrent": True,
        "entrypointCount": len(entries),
        "gitExecutableEntrypointCount": len(entries),
        "snapshotReleaseSha256": release_sha256,
        "detachedWorktreeCreated": False,
        "runtimeReplayExecuted": False,
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
    require("change-impact routing and static historical attestation" in active_root, "root gate label drift")
    require(f'"${{ROOT_DIR}}/scripts/{LATEST}"' in active_root, "latest attestation validator is not root")
    require(f'"${{ROOT_DIR}}/scripts/{PREDECESSOR}"' not in active_root, "predecessor remains root")
    for marker in (
        f'SNAPSHOT_COMMIT="{SNAPSHOT_COMMIT}"',
        "--verify-static-attestation",
        f'bash "${{ROOT_DIR}}/scripts/{PREDECESSOR}" --structure-only',
        "runtime replay was not executed",
    ):
        require(marker in validator, f"static attestation boundary missing: {marker}")
    for forbidden in (
        "worktree add",
        "mktemp",
        "V011_HISTORICAL_SNAPSHOT_ROOT",
        "V011_HISTORICAL_SNAPSHOT_COMMIT",
    ):
        require(forbidden not in validator, f"historical runtime replay restored: {forbidden}")
    require("V011_HISTORICAL_SNAPSHOT_ROOT" not in history, "dormant snapshot root adapter retained")
    require("V011_HISTORICAL_SNAPSHOT_COMMIT" not in history, "dormant snapshot commit adapter retained")
    require(f'"{LATEST}": PREDECESSOR' in topology_241, "v0.12.2.4.1 is not successor-aware")
    require(f'"{LATEST}": PREDECESSOR_ORCHESTRATOR' in topology_242, "v0.12.2.4.2 is not successor-aware")
    require(LATEST in predecessor, "release repair checker is not successor-aware")
    require("fetch-depth: 0" in workflow, "full Git history checkout removed")
    return {
        "status": "post-promotion-static-historical-attestation-validated",
        "snapshotCommit": SNAPSHOT_COMMIT,
        "v011EntrypointCount": len(manifest_entries(root)),
        "historicalRuntimeReplayEnabled": False,
        "detachedWorktreeEnabled": False,
        "currentV012StructureValidationPreserved": True,
        "requiredCheckPreserved": True,
        "workflowTriggersPreserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify-static-attestation", action="store_true")
    parser.add_argument("--snapshot-commit", default=SNAPSHOT_COMMIT)
    args = parser.parse_args()
    if args.verify_static_attestation:
        require(args.snapshot_commit == SNAPSHOT_COMMIT, "snapshot commit override prohibited")
        report = verify_static_attestation(args.root, args.snapshot_commit)
    else:
        report = validate_repository(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
