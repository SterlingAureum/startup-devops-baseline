#!/usr/bin/env python3
"""Offline tests for the strict lease-owned fixed-fake registry command."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import aws_two_wave_teardown_lease_registry_composition as COMPOSITION
import aws_two_wave_teardown_preflight as REQUEST


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.10-shared-dev-test-lease-registry-command"
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(ROOT / f"scripts/exercise-{PREFIX}.py", "lease_registry_command_under_test")
BASE = load(
    ROOT / "scripts/test-v0.12.4.1.5.0.7.1.6.9-shared-dev-test-lease-registry-composition.py",
    "lease_registry_composition_fixture_support",
)


class LeaseRegistryCommandTests(unittest.TestCase):
    def setUp(self):
        self.base = BASE.LeaseRegistryCompositionTests("test_success_writes_durable_claim_then_outcome")
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.request = self.base.execution_request()
        self.bindings = self.base.private_bindings(self.request)

    @staticmethod
    def private_file(value: dict, name: str):
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
        directory.chmod(0o700)
        path = directory / name
        path.write_bytes(REQUEST.canonical_bytes(value))
        path.chmod(0o600)
        return temporary, path

    def command_inputs(self):
        execution_temp, execution_root, _store = self.base.execution_store()
        request_temp, request_path = self.private_file(self.request, "execution-request.json")
        bindings_temp, bindings_path = self.private_file(self.bindings, "private-bindings.json")
        self.addCleanup(execution_temp.cleanup)
        self.addCleanup(request_temp.cleanup)
        self.addCleanup(bindings_temp.cleanup)
        args = [
            "--approval-store-directory", str(self.base.approval_store.root),
            "--execution-store-directory", str(execution_root),
            "--execution-request-file", str(request_path),
            "--private-bindings-file", str(bindings_path),
            "--expected-execution-request-sha256", REQUEST.sha256(self.request),
            "--expected-private-bindings-sha256", REQUEST.sha256(self.bindings),
            "--expected-receipt-sha256", self.base.receipt_sha,
            "--expected-approval-record-sha256", self.base.approval_record_sha,
            "--confirm", CLI.CONFIRMATION,
        ]
        return args, execution_root, request_path, bindings_path

    def test_exact_command_runs_one_durable_fixed_fake_attempt(self):
        args, execution_root, _request_path, _bindings_path = self.command_inputs()
        result = CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(result["environment"], "aws-dev")
        self.assertEqual(result["phase"], "wave-one-plan")
        self.assertEqual(result["backendCallCount"], 7)
        self.assertTrue(result["approvalConsumedByLease"])
        self.assertTrue(result["outcomeRecorded"])
        self.assertFalse(result["liveCommandExecuted"])
        self.assertEqual(len(list((execution_root / "claims").iterdir())), 1)
        self.assertEqual(len(list((execution_root / "outcomes").iterdir())), 1)

    def test_command_result_matches_stable_fixture(self):
        args, _root, _request_path, _bindings_path = self.command_inputs()
        result = CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(REQUEST.sha256(self.bindings), FIXTURE["expectedPrivateBindingsSha256"])
        self.assertEqual(REQUEST.sha256(result), FIXTURE["expectedCommandResultSha256"])

    def test_host_clock_is_read_exactly_once(self):
        args, _root, _request_path, _bindings_path = self.command_inputs()
        reads = []
        expected = self.base.execution_clock

        class OneClock:
            def now(self):
                reads.append(True)
                return expected

        original = CLI.SystemUtcClock
        CLI.SystemUtcClock = OneClock
        try:
            result = CLI.run(args)
        finally:
            CLI.SystemUtcClock = original
        self.assertEqual(len(reads), 1)
        self.assertEqual(result["backendCallCount"], 7)

    def test_second_command_attempt_stops_before_backend_dispatch(self):
        args, _root, _request_path, _bindings_path = self.command_inputs()
        CLI.run(args, now_utc=self.base.execution_clock)
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped) as stopped:
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(stopped.exception.report["backendCallCount"], 0)
        self.assertFalse(stopped.exception.report["claimCreated"])

    def test_wrong_confirmation_stops_before_private_file_read(self):
        args, execution_root, request_path, bindings_path = self.command_inputs()
        request_path.unlink()
        bindings_path.unlink()
        args[-1] = "wrong"
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_bad_expected_digest_stops_before_private_file_read(self):
        args, execution_root, request_path, bindings_path = self.command_inputs()
        request_path.unlink()
        bindings_path.unlink()
        index = args.index("--expected-private-bindings-sha256") + 1
        args[index] = "not-a-digest"
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_private_binding_digest_mismatch_stops_before_claim(self):
        args, execution_root, _request_path, _bindings_path = self.command_inputs()
        index = args.index("--expected-private-bindings-sha256") + 1
        args[index] = "f" * 64
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_execution_request_digest_mismatch_stops_before_claim(self):
        args, execution_root, _request_path, _bindings_path = self.command_inputs()
        index = args.index("--expected-execution-request-sha256") + 1
        args[index] = "f" * 64
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_private_file_mode_parent_mode_and_extra_entry_are_rejected(self):
        for mutation in ("file-mode", "parent-mode", "extra-entry"):
            with self.subTest(mutation=mutation):
                args, execution_root, request_path, _bindings_path = self.command_inputs()
                if mutation == "file-mode":
                    request_path.chmod(0o644)
                elif mutation == "parent-mode":
                    request_path.parent.chmod(0o755)
                    self.addCleanup(request_path.parent.chmod, 0o700)
                else:
                    extra = request_path.parent / "extra"
                    extra.write_text("extra")
                    extra.chmod(0o600)
                with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                    CLI.run(args, now_utc=self.base.execution_clock)
                self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_noncanonical_private_json_is_rejected(self):
        args, execution_root, request_path, _bindings_path = self.command_inputs()
        request_path.write_text(json.dumps(self.request, indent=2) + "\n")
        request_path.chmod(0o600)
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_private_input_paths_and_directories_must_be_distinct(self):
        args, execution_root, request_path, _bindings_path = self.command_inputs()
        binding_index = args.index("--private-bindings-file") + 1
        args[binding_index] = str(request_path)
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_relative_private_path_is_rejected(self):
        args, execution_root, _request_path, _bindings_path = self.command_inputs()
        request_index = args.index("--execution-request-file") + 1
        args[request_index] = "execution-request.json"
        with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
            CLI.run(args, now_utc=self.base.execution_clock)
        self.assertEqual(list((execution_root / "claims").iterdir()), [])

    def test_parser_exposes_no_failure_raw_command_or_live_switch(self):
        args, _root, _request_path, _bindings_path = self.command_inputs()
        for switch in ("--fail-at", "--command", "--endpoint", "--live", "--retry"):
            with self.subTest(switch=switch):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        CLI.parser().parse_args(args + [switch, "value"])

    def test_child_process_failure_is_generic_and_redacted(self):
        script = ROOT / f"scripts/exercise-{PREFIX}.py"
        result = subprocess.run(
            [
                sys.executable, str(script),
                "--approval-store-directory", "/private/approval",
                "--execution-store-directory", "/private/execution",
                "--execution-request-file", "/private/request/input.json",
                "--private-bindings-file", "/private/bindings/input.json",
                "--expected-execution-request-sha256", "1" * 64,
                "--expected-private-bindings-sha256", "2" * 64,
                "--expected-receipt-sha256", "3" * 64,
                "--expected-approval-record-sha256", "4" * 64,
                "--confirm", "wrong",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            "STOP: lease-owned fixed-fake registry command failed; preserve private stores and do not retry automatically.\n",
        )
        self.assertNotIn("/private/", result.stderr)
        self.assertNotIn("traceback", result.stderr.lower())

    def test_result_is_redacted(self):
        args, _root, _request_path, _bindings_path = self.command_inputs()
        raw = json.dumps(CLI.run(args, now_utc=self.base.execution_clock), sort_keys=True).lower()
        for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
            self.assertNotIn(marker, raw)
        self.assertNotIn("privatebindings", raw)


if __name__ == "__main__":
    unittest.main()
