from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ci_result", ROOT / "scripts/checks/ci_result.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


def results():
    value = {name: {"result": "success"} for name in ("route", "repository", "unit")}
    value.update({name: {"result": "skipped"} for name in ("application", "render", "platform", "iac", "promotion")})
    value["route"]["outputs"] = {"tests": "false", "render": "false", "platform": "false", "iac": "false", "environments": "[]"}
    return value


class AggregateTests(unittest.TestCase):
    def test_documentation_push_can_skip_inapplicable_work(self):
        ci.validate(results(), "push")

    def test_applicable_job_cannot_be_skipped(self):
        for output, job in (("tests", "application"), ("render", "render"), ("platform", "platform"), ("iac", "iac")):
            value = results()
            value["route"]["outputs"][output] = "true"
            value["route"]["outputs"]["environments"] = '["local"]'
            with self.subTest(job=job), self.assertRaises(ValueError): ci.validate(value, "push")
            value[job]["result"] = "success"
            ci.validate(value, "push")

    def test_pr_always_requires_promotion_policy_check(self):
        value = results()
        with self.assertRaises(ValueError): ci.validate(value, "pull_request")
        value["promotion"]["result"] = "success"
        ci.validate(value, "pull_request")

    def test_missing_route_and_cancelled_checks_are_rejected(self):
        for mutation in ("missing-output", "cancelled", "mandatory-skip", "empty-matrix"):
            value = results()
            if mutation == "missing-output": del value["route"]["outputs"]["iac"]
            elif mutation == "cancelled": value["render"]["result"] = "cancelled"
            elif mutation == "mandatory-skip": value["unit"]["result"] = "skipped"
            else:
                value["route"]["outputs"]["render"] = "true"
                value["render"]["result"] = "success"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): ci.validate(value, "push")


class TerraformEntrypointTests(unittest.TestCase):
    def test_moved_validation_keeps_all_five_roots_and_no_backend_access(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            log = directory / "calls.jsonl"
            tool = directory / "terraform"
            tool.write_text('#!/usr/bin/env python3\nimport json,os,sys\nwith open(os.environ["TF_TEST_CALL_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n')
            tool.chmod(0o700)
            environment = {**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"], "TF_TEST_CALL_LOG": str(log), "TERRAFORM_BIN": str(tool)}
            result = subprocess.run(["bash", "scripts/checks/terraform.sh"], cwd=ROOT, env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            initializes = [call for call in calls if "init" in call]
            self.assertEqual(len(initializes), 5)
            self.assertTrue(all("-backend=false" in call for call in initializes))
            self.assertEqual(len([call for call in calls if "validate" in call]), 5)
            self.assertFalse(any(word in call for call in calls for word in ("apply", "destroy", "plan", "-migrate-state")))
