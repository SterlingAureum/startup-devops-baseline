#!/usr/bin/env python3
"""Offline tests for the complete shared dev/test fresh-process chain."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import aws_two_wave_teardown_offline_process_chain as CHAIN
import aws_two_wave_teardown_phase_drivers as DRIVERS


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain"
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(ROOT / f"scripts/exercise-{PREFIX}.py", "offline_process_chain_cli_under_test")


class OfflineProcessChainTests(unittest.TestCase):
    def test_complete_chain_uses_sixteen_fresh_isolated_processes(self):
        real_run = subprocess.run
        calls = []

        def recording_run(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return real_run(arguments, **kwargs)

        with mock.patch.object(CHAIN.subprocess, "run", side_effect=recording_run):
            result = CHAIN.run_offline_process_chain(repository_root=ROOT)

        self.assertEqual(result["environmentOrder"], FIXTURE["expectedEnvironmentOrder"])
        self.assertEqual(result["phaseOrder"], FIXTURE["expectedPhaseOrder"])
        self.assertEqual(result["subprocessCallCount"], 16)
        self.assertEqual(result["completedPhaseCount"], 16)
        self.assertEqual(result["backendCallCount"], 98)
        self.assertEqual(len(calls), 16)
        self.assertEqual(
            [(row["environment"], row["phase"]) for row in result["phaseResults"]],
            [(environment, phase) for environment in CHAIN.ENVIRONMENTS for phase in DRIVERS.PHASE_OPERATIONS],
        )
        self.assertEqual(len({row["receiptSha256"] for row in result["phaseResults"]}), 16)
        self.assertEqual(len({row["claimSha256"] for row in result["phaseResults"]}), 16)
        self.assertEqual(len({row["outcomeSha256"] for row in result["phaseResults"]}), 16)
        expected_command = str(ROOT / "scripts" / CHAIN.COMMAND_FILENAME)
        for arguments, kwargs in calls:
            self.assertEqual(arguments[:2], [sys.executable, expected_command])
            self.assertEqual(kwargs["cwd"], ROOT)
            self.assertEqual(kwargs["env"], CHAIN._child_environment())
            self.assertEqual(kwargs["timeout"], 30)
            self.assertTrue(kwargs["capture_output"])
            self.assertFalse(kwargs["check"])
            self.assertNotIn("shell", kwargs)
            for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "KUBECONFIG", "TF_VAR_token", "GH_TOKEN"):
                self.assertNotIn(name, kwargs["env"])
        self.assertTrue(result["temporaryPrivateStoresRemoved"])
        self.assertFalse(result["liveCommandExecuted"])
        self.assertFalse(result["executionPerformed"])

    def test_temporary_private_tree_is_removed_after_success(self):
        real_temporary = tempfile.TemporaryDirectory
        created = []

        class RecordingTemporaryDirectory:
            def __init__(self, *args, **kwargs):
                self.inner = real_temporary(*args, **kwargs)
                created.append(Path(self.inner.name))

            def __enter__(self):
                return self.inner.__enter__()

            def __exit__(self, *args):
                return self.inner.__exit__(*args)

        with mock.patch.object(CHAIN.tempfile, "TemporaryDirectory", RecordingTemporaryDirectory):
            result = CHAIN.run_offline_process_chain(repository_root=ROOT)
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].exists())
        self.assertTrue(result["temporaryPrivateStoresRemoved"])

    def test_child_failure_stops_once_without_error_payload_or_retry(self):
        failed = subprocess.CompletedProcess(["synthetic"], 1, stdout=b"", stderr=b"/private/path secret")
        with mock.patch.object(CHAIN.subprocess, "run", return_value=failed) as child:
            with self.assertRaises(CHAIN.OfflineProcessChainStopped) as stopped:
                CHAIN.run_offline_process_chain(repository_root=ROOT)
        report = stopped.exception.report
        self.assertEqual(child.call_count, 1)
        self.assertEqual(report["subprocessCallCount"], 1)
        self.assertEqual(report["completedPhaseCount"], 0)
        self.assertEqual(report["environment"], "aws-dev")
        self.assertEqual(report["phase"], "controller-cleanup")
        self.assertFalse(report["automaticRetryPerformed"])
        raw = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("/private/", raw)
        self.assertNotIn("secret", raw)

    def test_timeout_stops_once_without_retry(self):
        timeout = subprocess.TimeoutExpired(["synthetic"], 30, output=b"private", stderr=b"private")
        with mock.patch.object(CHAIN.subprocess, "run", side_effect=timeout) as child:
            with self.assertRaises(CHAIN.OfflineProcessChainStopped) as stopped:
                CHAIN.run_offline_process_chain(repository_root=ROOT)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(stopped.exception.report["stage"], "fixed-command-process-timeout")
        self.assertEqual(stopped.exception.report["subprocessCallCount"], 1)
        self.assertFalse(stopped.exception.report["automaticRetryPerformed"])

    def test_noncanonical_or_malformed_child_output_stops(self):
        malformed = subprocess.CompletedProcess(["synthetic"], 0, stdout=b"{}\n", stderr=b"")
        with mock.patch.object(CHAIN.subprocess, "run", return_value=malformed) as child:
            with self.assertRaises(CHAIN.OfflineProcessChainStopped) as stopped:
                CHAIN.run_offline_process_chain(repository_root=ROOT)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(stopped.exception.report["completedPhaseCount"], 0)

    def test_repository_root_must_be_absolute_and_contain_exact_command(self):
        with mock.patch.object(CHAIN.subprocess, "run") as child:
            with self.assertRaises(CHAIN.OfflineProcessChainStopped):
                CHAIN.run_offline_process_chain(repository_root=Path("relative"))
            with tempfile.TemporaryDirectory() as empty:
                with self.assertRaises(CHAIN.OfflineProcessChainStopped):
                    CHAIN.run_offline_process_chain(repository_root=Path(empty))
        child.assert_not_called()

    def test_cli_exposes_only_confirmation_and_rejects_wrong_value_preflight(self):
        options = {
            option
            for action in CLI.parser()._actions
            for option in action.option_strings
            if option not in ("-h", "--help")
        }
        self.assertEqual(options, {"--confirm"})
        with mock.patch.object(CHAIN, "run_offline_process_chain") as chain:
            with self.assertRaises(CHAIN.OfflineProcessChainStopped):
                CLI.run(["--confirm", "wrong"])
        chain.assert_not_called()

    def test_result_and_stop_contracts_are_redacted(self):
        result = CHAIN.run_offline_process_chain(repository_root=ROOT)
        stop = CHAIN.OfflineProcessChainStopped(
            "synthetic-stage", environment="aws-dev", phase="wave-one-plan"
        ).report
        for value in (result, stop):
            raw = json.dumps(value, sort_keys=True).lower()
            for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-", "privatebindings"):
                self.assertNotIn(marker, raw)
            self.assertFalse(value["liveCommandExecuted"])
            self.assertFalse(value["executionPerformed"])


if __name__ == "__main__":
    unittest.main()
