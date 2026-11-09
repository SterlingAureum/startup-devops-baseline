from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("repository_checks", ROOT / "scripts/checks/repository.py")
repository = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository)


class WorkflowCheckoutTests(unittest.TestCase):
    def job(self):
        document = yaml.load((ROOT / ".github/workflows/delivery-validate.yaml").read_text(), Loader=yaml.BaseLoader)
        return document["jobs"]["quality-gates"]

    def test_actual_aggregate_job_checks_out_before_using_script(self):
        repository.check_job_checkout(self.job(), "quality-gates")

    def test_missing_checkout_is_rejected(self):
        job = self.job()
        job["steps"] = [step for step in job["steps"] if not step.get("uses", "").startswith("actions/checkout@")]
        with self.assertRaisesRegex(ValueError, "before checkout"):
            repository.check_job_checkout(job, "quality-gates")

    def test_checkout_after_script_is_rejected(self):
        job = self.job()
        job["steps"].reverse()
        with self.assertRaisesRegex(ValueError, "before checkout"):
            repository.check_job_checkout(job, "quality-gates")

    def test_checkout_in_another_job_does_not_count(self):
        repository.check_job_checkout({"steps": [{"uses": "actions/checkout@" + "a" * 40}]}, "first-job")
        with self.assertRaises(ValueError):
            repository.check_job_checkout({"steps": [{"run": "python3 scripts/checks/ci_result.py"}]}, "second-job")

    def test_inline_only_and_reusable_jobs_need_no_checkout(self):
        repository.check_job_checkout({"steps": [{"run": "test -n \"${TOKEN}\""}]}, "inline-only")
        repository.check_job_checkout({"uses": "./.github/workflows/delivery-verify.yaml"}, "reusable-call")

    def test_aggregate_runs_in_fresh_workspace_after_files_are_checked_out(self):
        # Reproduce the filesystem boundary of a new runner without contacting
        # GitHub: no scripts before checkout, then materialize the required file.
        results = {name: {"result": "success"} for name in ("route", "repository", "unit")}
        results.update({name: {"result": "skipped"} for name in ("application", "render", "platform", "iac", "promotion")})
        results["route"]["outputs"] = {"tests": "false", "render": "false", "platform": "false", "iac": "false", "environments": "[]"}
        environment = {**os.environ, "RESULTS": json.dumps(results), "GITHUB_EVENT_NAME": "push"}
        with tempfile.TemporaryDirectory() as directory:
            command = ["python3", "scripts/checks/ci_result.py"]
            missing = subprocess.run(command, cwd=directory, env=environment, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)
            script = Path(directory) / "scripts/checks/ci_result.py"
            script.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/checks/ci_result.py", script)
            success = subprocess.run(command, cwd=directory, env=environment, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            # Actual business-check failure must still fail after the checkout fix.
            results["unit"]["result"] = "failure"
            environment["RESULTS"] = json.dumps(results)
            failure = subprocess.run(command, cwd=directory, env=environment, capture_output=True, text=True)
            self.assertEqual(failure.returncode, 1, failure.stdout + failure.stderr)
