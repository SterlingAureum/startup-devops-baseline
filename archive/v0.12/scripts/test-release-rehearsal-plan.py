#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preflight", ROOT / "scripts/check-release-rehearsal-plan.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(environment="local", branch=MODULE.BRANCH, source_commit="a" * 40,
                         context="kind-local", review_reference="test-123", operator="tester",
                         recovery_owner="tester", evidence_directory="/tmp/private-evidence",
                         approval_policy="human-governed", max_duration_seconds=900,
                         failure_scenario="candidate-slo-gate-rejection",
                         baseline=dict(application_version="baseline-1", image="example.invalid/demo@sha256:" + "b" * 64),
                         candidate=dict(application_version="candidate-2", image="example.invalid/demo@sha256:" + "b" * 64))

    def test_valid_environments_do_not_authorize(self):
        for env in ("local", "aws-dev", "aws-test"):
            self.plan["environment"] = env
            result = MODULE.validate(self.plan)
            self.assertFalse(result["execution_authorized"])
            self.assertFalse(result["runtime_qualified"])

    def test_rejections(self):
        for key, value in (("environment", "aws-prod"), ("branch", "main"),
                           ("source_commit", "short"), ("operator", ""),
                           ("context", "REPLACE_CONTEXT"), ("review_reference", None),
                           ("evidence_directory", "relative"), ("approval_policy", "automatic"),
                           ("max_duration_seconds", True), ("max_duration_seconds", 3601),
                           ("failure_scenario", "delete-pods"), ("baseline", [])):
            with self.subTest(key=key, value=value):
                plan = copy.deepcopy(self.plan)
                plan[key] = value
                with self.assertRaises(ValueError):
                    MODULE.validate(plan)

    def test_missing_extra_wrong_type(self):
        for plan in ([], {**self.plan, "execute": True}, {k: v for k, v in self.plan.items() if k != "context"}):
            with self.assertRaises(ValueError):
                MODULE.validate(plan)

    def test_release_identity(self):
        for key, value in (("image", "demo:latest"), ("application_version", "baseline-1"),
                           ("application_version", "REPLACE_CANDIDATE")):
            plan = copy.deepcopy(self.plan)
            plan["candidate"][key] = value
            with self.assertRaises(ValueError):
                MODULE.validate(plan)

    def test_template_rejected_cli(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/check-release-rehearsal-plan.py"),
                                 "--plan", str(ROOT / "delivery/examples/release-rehearsal-plan.json")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Plan rejected", result.stderr)

    def test_contract(self):
        contract = json.loads((ROOT / "delivery/contracts/v0.11.9.0-release-rehearsal-design.json").read_text())
        self.assertFalse(contract["runtime_qualified"])
        self.assertFalse(contract["execution_authorized"])
        self.assertEqual(len(contract["scenarios"]), 4)
        self.assertEqual(contract["prod"], "deferred-to-v0.11-tail")


if __name__ == "__main__":
    unittest.main()
