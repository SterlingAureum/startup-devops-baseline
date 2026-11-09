#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.11.9.3.6.7.4-aws-test-gitops-bootstrap.py"
SPEC = importlib.util.spec_from_file_location("aws_test_gitops_bootstrap", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-test GitOps bootstrap executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ACCOUNT = "123456789012"


class Runner:
    def __init__(self, post_bootstrap: bool = False) -> None:
        self.post_bootstrap = post_bootstrap
        self.calls: list[list[str]] = []

    def __call__(self, arguments, environment, timeout):
        self.calls.append(arguments)
        joined = " ".join(arguments)
        if arguments == [str(MODULE.BOOTSTRAP)]:
            self.post_bootstrap = True
            return subprocess.CompletedProcess(arguments, 0, b"bootstrap complete\n", b"")
        if "get-caller-identity" in joined:
            body = {"Account": ACCOUNT}
        elif "list-clusters" in joined:
            body = {"clusters": [MODULE.CLUSTER_NAME]}
        elif "describe-cluster" in joined:
            body = {
                "cluster": {
                    "name": MODULE.CLUSTER_NAME,
                    "status": "ACTIVE",
                    "endpoint": "https://reviewed.test.eks.amazonaws.com",
                    "resourcesVpcConfig": {"publicAccessCidrs": ["8.8.8.8/32"]},
                }
            }
        elif "describe-secret" in joined:
            body = {"Name": MODULE.SECRET_NAME}
        elif "state list" in joined:
            return subprocess.CompletedProcess(arguments, 0, ("address\n" * 103).encode(), b"")
        elif "config view" in joined:
            body = {"clusters": [{"cluster": {"server": "https://reviewed.test.eks.amazonaws.com"}}]}
        elif "--raw=/readyz" in joined:
            return subprocess.CompletedProcess(arguments, 0, b"ok\n", b"")
        elif "aws_load_balancer_controller_role_arn" in joined:
            return subprocess.CompletedProcess(arguments, 0, f"arn:aws:iam::{ACCOUNT}:role/alb\n".encode(), b"")
        elif "karpenter_controller_role_arn" in joined:
            return subprocess.CompletedProcess(arguments, 0, f"arn:aws:iam::{ACCOUNT}:role/karpenter\n".encode(), b"")
        elif "namespace argocd" in joined:
            if self.post_bootstrap:
                body = {"metadata": {"name": "argocd"}}
            else:
                return subprocess.CompletedProcess(arguments, 1, b"", b"Error from server (NotFound)")
        elif "serviceaccount" in joined:
            if not self.post_bootstrap:
                return subprocess.CompletedProcess(arguments, 1, b"", b"Error from server (NotFound)")
            name = "aws-load-balancer-controller" if "aws-load-balancer-controller" in arguments else "karpenter"
            body = {
                "metadata": {
                    "name": name,
                    "annotations": {"eks.amazonaws.com/role-arn": f"arn:aws:iam::{ACCOUNT}:role/{'alb' if name.startswith('aws-') else 'karpenter'}"},
                }
            }
        elif "application startup-devops-aws-test-root" in joined:
            return subprocess.CompletedProcess(arguments, 1, b"", b"Error from server (NotFound)")
        elif "application aws-load-balancer-controller" in joined:
            body = {"metadata": {"name": MODULE.ALB_APPLICATION}}
        elif "deployment" in arguments or "statefulset" in arguments:
            body = {"status": {"readyReplicas": 1}}
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")


class LiveChecksTests(unittest.TestCase):
    def context(self):
        return {
            "account_id": ACCOUNT,
            "management_cidr": "8.8.8.8/32",
            "expected_main": "f" * 40,
            "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
            "remaining": 10000,
        }

    def test_preflight_is_read_only_and_requires_empty_bootstrap_surface(self):
        runner = Runner()
        MODULE.live_checks(self.context(), runner)
        commands = [" ".join(call) for call in runner.calls]
        self.assertFalse(any("terraform apply" in command or "terraform plan" in command for command in commands))
        self.assertFalse(any(call == [str(MODULE.BOOTSTRAP)] for call in runner.calls))

    def test_rejects_foreign_rehearsal_cluster(self):
        runner = Runner()
        original = runner.__call__

        def foreign(arguments, environment, timeout):
            if "list-clusters" in arguments:
                body = {"clusters": [MODULE.CLUSTER_NAME, "startup-devops-baseline-dev"]}
                return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")
            return original(arguments, environment, timeout)

        with self.assertRaisesRegex(ValueError, "only the aws-test"):
            MODULE.live_checks(self.context(), foreign)

    def test_rejects_wrong_api_cidr(self):
        runner = Runner()
        context = self.context()
        context["management_cidr"] = "9.9.9.9/32"
        with self.assertRaisesRegex(ValueError, "public CIDR"):
            MODULE.live_checks(context, runner)

    def test_rejects_existing_argocd_namespace_before_execution(self):
        with self.assertRaisesRegex(ValueError, "must be absent"):
            MODULE.live_checks(self.context(), Runner(post_bootstrap=True), post_bootstrap=False)

    def test_post_bootstrap_requires_root_application_absent(self):
        runner = Runner(post_bootstrap=True)
        original = runner.__call__

        def root_present(arguments, environment, timeout):
            if "startup-devops-aws-test-root" in arguments:
                return subprocess.CompletedProcess(arguments, 0, json.dumps({"metadata": {"name": MODULE.ROOT_APPLICATION}}).encode(), b"")
            return original(arguments, environment, timeout)

        with self.assertRaisesRegex(ValueError, "Root Application"):
            MODULE.live_checks(self.context(), root_present, post_bootstrap=True)


class PhaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name) / "private"
        self.parent.mkdir(mode=0o700)
        self.output = self.parent / "bootstrap"
        self.state = Path(self.temp.name) / "terraform.tfstate"
        self.state.write_text("state\n")
        self.state.chmod(0o600)
        self.context = {
            "account_id": ACCOUNT,
            "management_cidr": "8.8.8.8/32",
            "expected_main": "f" * 40,
            "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
            "remaining": 10000,
            "state_path": self.state,
        }

    def tearDown(self):
        self.temp.cleanup()

    def environment(self, execute=False, **extra):
        values = {
            "AWS_ENVIRONMENT": "aws-test",
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_TEST_GITOPS_BOOTSTRAP_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
        }
        if execute:
            values["CONFIRM_AWS_TEST_GITOPS_BOOTSTRAP_EXECUTION"] = MODULE.EXECUTION_CONFIRMATION
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=True)

    def test_verify_never_authorizes_mutation(self):
        with self.environment():
            result = MODULE.verify_phase(self.context, Runner())
        self.assertEqual(result["status"], "aws-test-gitops-bootstrap-inputs-verified")
        self.assertFalse(result["gitops_bootstrap_authorized"])
        self.assertFalse(result["kubernetes_mutation_executed"])

    def test_execute_requires_separate_confirmation_before_commands(self):
        reviewed = self.parent / "verify.json"
        reviewed.write_text(json.dumps({"status": "aws-test-gitops-bootstrap-inputs-verified", "control_plane_commit": "f" * 40}))
        reviewed.chmod(0o600)
        digest = hashlib.sha256(reviewed.read_bytes()).hexdigest()
        runner = Runner()
        with self.environment(), self.assertRaisesRegex(ValueError, "execution confirmation"):
            MODULE.execute_phase(self.context, self.output, reviewed, digest, runner)
        self.assertEqual(runner.calls, [])

    def test_execute_runs_exact_bootstrap_once_and_stops_before_root(self):
        reviewed = self.parent / "verify.json"
        reviewed.write_text(json.dumps({"status": "aws-test-gitops-bootstrap-inputs-verified", "control_plane_commit": "f" * 40}))
        reviewed.chmod(0o600)
        digest = hashlib.sha256(reviewed.read_bytes()).hexdigest()
        runner = Runner()
        state_digest = hashlib.sha256(self.state.read_bytes()).hexdigest()
        with self.environment(execute=True), mock.patch.object(MODULE, "STATE_SHA256", state_digest):
            result = MODULE.execute_phase(self.context, self.output, reviewed, digest, runner)
        self.assertEqual(sum(call == [str(MODULE.BOOTSTRAP)] for call in runner.calls), 1)
        self.assertEqual(result["status"], "aws-test-gitops-bootstrap-complete")
        self.assertFalse(result["root_application_deployed"])
        self.assertFalse(result["terraform_apply_executed"])
        self.assertFalse(result["automatic_retry_performed"])
        self.assertEqual(oct(self.output.stat().st_mode & 0o777), "0o700")
        self.assertTrue(all((path.stat().st_mode & 0o777) == 0o600 for path in self.output.iterdir()))

    def test_legacy_bootstrap_confirmation_is_rejected(self):
        reviewed = self.parent / "verify.json"
        reviewed.write_text(json.dumps({"status": "aws-test-gitops-bootstrap-inputs-verified", "control_plane_commit": "f" * 40}))
        reviewed.chmod(0o600)
        digest = hashlib.sha256(reviewed.read_bytes()).hexdigest()
        with self.environment(execute=True, CONFIRM_AWS_TEST_BOOTSTRAP="bootstrap-ephemeral-aws-test"):
            with self.assertRaisesRegex(ValueError, "must be unset"):
                MODULE.execute_phase(self.context, self.output, reviewed, digest, Runner())

    def test_deadline_requires_fifteen_minutes(self):
        deadline = datetime.fromisoformat(MODULE.SESSION_DEADLINE_UTC.replace("Z", "+00:00"))
        self.assertLess(int((deadline - datetime(2026, 9, 12, 17, 24, tzinfo=timezone.utc)).total_seconds()), MODULE.MINIMUM_REMAINING_SECONDS)


if __name__ == "__main__":
    unittest.main()
