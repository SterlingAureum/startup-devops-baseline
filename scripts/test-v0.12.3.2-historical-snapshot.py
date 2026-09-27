#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("check-v0.12.3.2-historical-snapshot.py")
SPEC = importlib.util.spec_from_file_location("historical_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StaticAttestationTests(unittest.TestCase):
    def make_fixture(self, root: Path, executable: bool = True) -> tuple[Path, str, str]:
        current = root / "current"
        (current / "scripts").mkdir(parents=True)
        manifest = current / MODULE.MANIFEST
        manifest.parent.mkdir(parents=True)
        names = [f"validate-v0.11.{index:03d}-fixture.sh" for index in range(112)]
        manifest.write_text("\n".join(names) + "\n")
        for name in names:
            path = current / "scripts" / name
            path.write_text("#!/usr/bin/env bash\nexit 0\n")
            path.chmod(0o755 if executable else 0o644)
        release = current / MODULE.SNAPSHOT_RELEASE
        release.parent.mkdir(parents=True)
        release.write_text("image:\n  tag: fixture\n")
        release_sha256 = hashlib.sha256(release.read_bytes()).hexdigest()
        subprocess.run(["git", "init", "-q", str(current)], check=True)
        subprocess.run(["git", "-C", str(current), "config", "user.name", "Snapshot Test"], check=True)
        subprocess.run(["git", "-C", str(current), "config", "user.email", "snapshot@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(current), "add", "."], check=True)
        subprocess.run(["git", "-C", str(current), "commit", "-q", "-m", "snapshot"], check=True)
        snapshot_commit = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (current / "current.txt").write_text("current\n")
        subprocess.run(["git", "-C", str(current), "add", "current.txt"], check=True)
        subprocess.run(["git", "-C", str(current), "commit", "-q", "-m", "current"], check=True)
        return current, snapshot_commit, release_sha256

    def test_exact_static_attestation_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, commit, release_sha256 = self.make_fixture(Path(temp))
            report = MODULE.verify_static_attestation(
                current, commit, expected_release_sha256=release_sha256
            )
            self.assertEqual(report["entrypointCount"], 112)
            self.assertTrue(report["snapshotAncestor"])
            self.assertFalse(report["detachedWorktreeCreated"])
            self.assertFalse(report["runtimeReplayExecuted"])

    def test_current_manifest_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, commit, release_sha256 = self.make_fixture(Path(temp))
            (current / MODULE.MANIFEST).write_text("validate-v0.11.999-fixture.sh\n")
            with self.assertRaisesRegex(MODULE.SnapshotError, "entrypoint count drift"):
                MODULE.verify_static_attestation(
                    current, commit, expected_release_sha256=release_sha256
                )

    def test_non_executable_git_entrypoint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, commit, release_sha256 = self.make_fixture(Path(temp), executable=False)
            with self.assertRaisesRegex(MODULE.SnapshotError, "mode drift"):
                MODULE.verify_static_attestation(
                    current, commit, expected_release_sha256=release_sha256
                )

    def test_snapshot_release_digest_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, commit, _release_sha256 = self.make_fixture(Path(temp))
            with self.assertRaisesRegex(MODULE.SnapshotError, "release digest drift"):
                MODULE.verify_static_attestation(
                    current, commit, expected_release_sha256="0" * 64
                )

    def test_invalid_snapshot_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, _commit, release_sha256 = self.make_fixture(Path(temp))
            with self.assertRaisesRegex(MODULE.SnapshotError, "invalid snapshot commit"):
                MODULE.verify_static_attestation(
                    current, "not-a-commit", expected_release_sha256=release_sha256
                )


class RepositoryTests(unittest.TestCase):
    def test_repository_has_static_attestation_without_runtime_replay(self) -> None:
        report = MODULE.validate_repository(SCRIPT.parents[1])
        self.assertEqual(report["snapshotCommit"], MODULE.SNAPSHOT_COMMIT)
        self.assertEqual(report["v011EntrypointCount"], 112)
        self.assertFalse(report["historicalRuntimeReplayEnabled"])
        self.assertFalse(report["detachedWorktreeEnabled"])
        self.assertTrue(report["currentV012StructureValidationPreserved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
