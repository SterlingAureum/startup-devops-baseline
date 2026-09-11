#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
import importlib.util, json, os
from pathlib import Path
import tempfile, unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.11.9.3.6.6.5.1-aws-dev-teardown.py"
spec = importlib.util.spec_from_file_location("executor", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = "1dc2bd44a123931fc56e808110179b9e6d902a11"
NOW = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)


def result():
    return {
        "status": "aws-dev-teardown-preflight-ready-for-separate-approval",
        "control_plane_commit": SHA,
        "execution_authorized": False,
        "teardown_authorized": False,
        "mutation_executed": False,
    }


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.directory.chmod(0o700)
        self.path = self.directory / "preflight.json"
        self.path.write_text(json.dumps(result()))
        self.path.chmod(0o600)
        self.digest = __import__("hashlib").sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, mode="verify", destroy=lambda: 0):
        return module.execute(mode, SHA, self.path, self.digest,
                              "2026-09-11T03:00:00Z", "2026-09-11T06:00:00Z",
                              now=NOW, preflight=lambda _sha: result(), destroy=destroy)

    def test_verify_never_destroys(self):
        called = []
        output = self.call(destroy=lambda: called.append(True) or 0)
        self.assertFalse(output["execution_authorized"])
        self.assertFalse(output["teardown_executed"])
        self.assertEqual(called, [])

    def test_execute_requires_separate_confirmation(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "confirmation"): self.call("execute")

    def test_execute_calls_destroy_once_after_gates(self):
        called = []
        with mock.patch.dict(os.environ, {"CONFIRM_AWS_DEV_TEARDOWN_EXECUTION": module.EXECUTION_CONFIRMATION}, clear=True):
            output = self.call("execute", lambda: called.append(True) or 0)
        self.assertTrue(output["teardown_executed"])
        self.assertEqual(called, [True])

    def test_expired_window_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            module.execute("verify", SHA, self.path, self.digest,
                           "2026-09-11T00:00:00Z", "2026-09-11T01:00:00Z",
                           now=NOW, preflight=lambda _sha: result())

    def test_changed_immediate_preflight_rejected(self):
        changed = result(); changed["terraform_resource_count"] = 102
        with self.assertRaisesRegex(ValueError, "does not match"):
            module.execute("verify", SHA, self.path, self.digest,
                           "2026-09-11T03:00:00Z", "2026-09-11T06:00:00Z",
                           now=NOW, preflight=lambda _sha: changed)


if __name__ == "__main__": unittest.main()
