#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("check-v0.12.3.2-historical-snapshot.py")
SPEC = importlib.util.spec_from_file_location("historical_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SnapshotTests(unittest.TestCase):
    def make_fixture(self, root: Path, executable: bool = True) -> tuple[Path, Path, str]:
        current = root / "current"
        snapshot = root / "snapshot"
        (current / "scripts").mkdir(parents=True)
        manifest = current / MODULE.MANIFEST
        manifest.parent.mkdir(parents=True)
        names = [f"validate-v0.11.{index:03d}-fixture.sh" for index in range(112)]
        manifest.write_text("\n".join(names) + "\n")
        for name in names:
            path = current / "scripts" / name
            path.write_text("#!/usr/bin/env bash\nexit 0\n")
            path.chmod(0o755 if executable else 0o644)
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
        subprocess.run(
            ["git", "-C", str(current), "worktree", "add", "--quiet", "--detach", str(snapshot), snapshot_commit],
            check=True,
        )
        return current, snapshot, snapshot_commit

    def test_exact_snapshot_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp))
            report = MODULE.verify_snapshot(current, snapshot, commit)
            self.assertEqual(report["entrypointCount"], 112)
            self.assertTrue(report["snapshotAncestor"])

    def test_snapshot_head_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp))
            current_head = subprocess.run(
                ["git", "-C", str(current), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            with self.assertRaisesRegex(MODULE.SnapshotError, "snapshot HEAD drift"):
                MODULE.verify_snapshot(current, snapshot, current_head)

    def test_dirty_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp))
            first = next((snapshot / "scripts").glob("validate-v0.11*.sh"))
            first.write_text("changed\n")
            with self.assertRaisesRegex(MODULE.SnapshotError, "worktree dirty"):
                MODULE.verify_snapshot(current, snapshot, commit)

    def test_manifest_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp))
            (current / MODULE.MANIFEST).write_text("validate-v0.11.999-fixture.sh\n")
            with self.assertRaisesRegex(MODULE.SnapshotError, "manifest drift"):
                MODULE.verify_snapshot(current, snapshot, commit)

    def test_non_executable_entrypoint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp), executable=False)
            with self.assertRaisesRegex(MODULE.SnapshotError, "mode drift"):
                MODULE.verify_snapshot(current, snapshot, commit)

    def test_snapshot_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current, snapshot, commit = self.make_fixture(Path(temp))
            first = next((snapshot / "scripts").glob("validate-v0.11*.sh"))
            first.unlink()
            first.symlink_to("validate-v0.11.001-fixture.sh")
            with self.assertRaisesRegex(MODULE.SnapshotError, "worktree dirty"):
                MODULE.verify_snapshot(current, snapshot, commit)


class RepositoryTests(unittest.TestCase):
    def test_repository_has_exact_snapshot_orchestration(self) -> None:
        report = MODULE.validate_repository(SCRIPT.parents[1])
        self.assertEqual(report["snapshotCommit"], MODULE.SNAPSHOT_COMMIT)
        self.assertEqual(report["v011EntrypointCount"], 112)
        self.assertTrue(report["currentV012ValidationPreserved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
