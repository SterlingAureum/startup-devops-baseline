#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("check-v0.12.2.4.2-quality-gate-orchestration.py")
HELPER = Path(__file__).with_name("check-tracked-terraform-format.sh")
SPEC = importlib.util.spec_from_file_location("quality_gate_orchestration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ParserTests(unittest.TestCase):
    def test_ignores_heredocs_and_bash_n_arguments(self) -> None:
        text = """#!/usr/bin/env bash
: <<'MANIFEST'
"${ROOT_DIR}/scripts/validate-v0.11.9-hidden.sh"
MANIFEST
bash -n \\
  "${ROOT_DIR}/scripts/validate-v0.11.8-syntax-only.sh"
bash "${ROOT_DIR}/scripts/validate-v0.11.7-executed.sh"
"""
        self.assertEqual(
            MODULE.extract_validator_calls(text),
            ["validate-v0.11.7-executed.sh"],
        )

    def test_rejects_cycle(self) -> None:
        with self.assertRaisesRegex(MODULE.TopologyError, "cycle"):
            MODULE.expansion_counts(
                {"a.sh": ["b.sh"], "b.sh": ["a.sh"]}, ["a.sh"]
            )


class TrackedTerraformFormatTests(unittest.TestCase):
    def make_fixture(self, directory: Path) -> tuple[Path, Path]:
        (directory / "scripts").mkdir()
        helper = directory / "scripts/check-tracked-terraform-format.sh"
        shutil.copy2(HELPER, helper)
        helper.chmod(0o755)
        tf_root = directory / "infra/terraform/aws/example"
        tf_root.mkdir(parents=True)
        (tf_root / "main.tf").write_text("terraform {}\n")
        (tf_root / "tracked.auto.tfvars").write_text("name = \"tracked\"\n")
        (tf_root / "terraform.tfvars").write_text("name = \"private\"\n")
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        subprocess.run(
            ["git", "-C", str(directory), "add", "scripts", "infra/terraform/aws/example/main.tf", "infra/terraform/aws/example/tracked.auto.tfvars"],
            check=True,
        )
        fake = directory / "fake-terraform"
        fake.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >"${FAKE_TERRAFORM_LOG}"\n')
        fake.chmod(0o755)
        return helper, fake

    def test_only_tracked_terraform_files_are_passed_to_fmt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            helper, fake = self.make_fixture(directory)
            log = directory / "arguments.log"
            environment = os.environ.copy()
            environment.update(TERRAFORM_BIN=str(fake), FAKE_TERRAFORM_LOG=str(log))
            subprocess.run([str(helper)], cwd=directory, env=environment, check=True)
            arguments = log.read_text().splitlines()
            self.assertEqual(arguments[:3], ["fmt", "-check", "-no-color"])
            self.assertEqual(
                arguments[3:],
                [
                    "infra/terraform/aws/example/main.tf",
                    "infra/terraform/aws/example/tracked.auto.tfvars",
                ],
            )
            self.assertNotIn("infra/terraform/aws/example/terraform.tfvars", arguments)

    def test_optional_mode_skips_when_terraform_is_unavailable(self) -> None:
        environment = os.environ.copy()
        environment["TERRAFORM_BIN"] = "terraform-command-that-does-not-exist"
        result = subprocess.run(
            [str(HELPER), "--optional"],
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIP: terraform unavailable", result.stdout)


class RepositoryTests(unittest.TestCase):
    def test_exact_repository_topology(self) -> None:
        report = MODULE.validate_repository(SCRIPT.parents[1])
        self.assertEqual(report["root_direct_validator_count"], 29)
        self.assertEqual(report["delegated_v0_11_entrypoint_count"], 112)
        self.assertEqual(report["unique_reachable_v0_11_validator_count"], 168)
        self.assertEqual(report["effective_v0_11_validator_execution_count"], 176)
        self.assertEqual(report["effective_v0_12_orchestration_execution_count"], 3)
        self.assertEqual(report["effective_validator_execution_count"], 246)


if __name__ == "__main__":
    unittest.main(verbosity=2)
