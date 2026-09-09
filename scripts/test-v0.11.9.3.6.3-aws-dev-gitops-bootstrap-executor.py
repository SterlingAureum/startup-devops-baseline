#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.3-aws-dev-gitops-bootstrap.py"
SPEC = importlib.util.spec_from_file_location("aws_dev_gitops_bootstrap", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev GitOps bootstrap executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONTROL_PLANE = "a" * 40
ACCOUNT = "123456789012"


class Fixture:
    def __init__(self) -> None:
        self.git_values = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): CONTROL_PLANE,
            ("rev-parse", "origin/main"): CONTROL_PLANE,
        }
        self.state = [f"module.fixture.resource[{index}]" for index in range(102)]
        self.state.append("module.eks.aws_eks_cluster.this[0]")
        self.read_values = {
            ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"): ACCOUNT,
            (
                "aws", "eks", "describe-cluster", "--region", "us-east-1", "--name",
                "startup-devops-baseline-dev", "--query", "cluster.[status,version,endpoint]", "--output", "text",
            ): "ACTIVE\t1.36\thttps://eks.example.invalid",
            (
                "kubectl", "config", "view", "--minify", "-o",
                "jsonpath={.clusters[0].cluster.server}",
            ): "https://eks.example.invalid",
            ("kubectl", "get", "--raw=/readyz"): "ok",
            ("kubectl", "get", "namespace", "argocd", "--ignore-not-found", "-o", "name"): "",
        }
        self.read_calls: list[tuple[str, ...]] = []

    def git_runner(self, arguments: list[str]) -> str:
        return self.git_values[tuple(arguments)]

    def read_runner(self, arguments: list[str]) -> str:
        key = tuple(str(value) for value in arguments)
        self.read_calls.append(key)
        if key[:2] == ("terraform", f"-chdir={MODULE.TF_DIR}"):
            if key[2:] == ("state", "list"):
                return "\n".join(self.state)
            output_name = key[-1]
            outputs = {
                "aws_load_balancer_controller_role_arn": f"arn:aws:iam::{ACCOUNT}:role/alb",
                "karpenter_controller_role_arn": f"arn:aws:iam::{ACCOUNT}:role/karpenter",
                "vpc_id": "vpc-0123abc",
            }
            return outputs[output_name]
        return self.read_values[key]


class AwsDevGitopsBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.controls = {
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_DEV_GITOPS_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
        }

    def verify(self):
        with mock.patch.dict(os.environ, self.controls, clear=True):
            return MODULE.verify_live_inputs(
                CONTROL_PLANE,
                self.fixture.git_runner,
                self.fixture.read_runner,
            )

    def test_verify_accepts_only_expected_read_only_inventory(self) -> None:
        inventory = self.verify()
        result = MODULE.verification_result(inventory)
        self.assertEqual(result["status"], "aws-dev-gitops-bootstrap-inputs-verified")
        self.assertEqual(result["terraform_state_address_count"], 103)
        self.assertFalse(result["argocd_namespace_present"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("aws_account_id", result)
        self.assertNotIn("vpc_id", result)
        self.assertEqual(len(self.fixture.read_calls), 9)

    def test_observation_confirmation_and_account_format_are_required(self) -> None:
        with mock.patch.dict(os.environ, {"EXPECTED_AWS_ACCOUNT_ID": ACCOUNT}, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_GITOPS_PREFLIGHT"):
                MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)
        with mock.patch.dict(
            os.environ,
            {
                "EXPECTED_AWS_ACCOUNT_ID": "not-an-account",
                "CONFIRM_AWS_DEV_GITOPS_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "12-digit"):
                MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)

    def test_exact_clean_main_is_required_before_live_reads(self) -> None:
        for key, value, message in (
            (("branch", "--show-current"), "feature/demo", "from main"),
            (("status", "--porcelain"), " M README.md", "clean worktree"),
            (("rev-parse", "origin/main"), "b" * 40, "reviewed commit"),
        ):
            with self.subTest(key=key):
                fixture = Fixture()
                fixture.git_values[key] = value
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)
                self.assertEqual(fixture.read_calls, [])

    def test_account_cluster_state_api_and_namespace_fail_closed(self) -> None:
        cases = (
            ("account", lambda f: f.read_values.__setitem__(("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"), "999999999999"), "caller account"),
            ("cluster", lambda f: f.read_values.__setitem__(("aws", "eks", "describe-cluster", "--region", "us-east-1", "--name", "startup-devops-baseline-dev", "--query", "cluster.[status,version,endpoint]", "--output", "text"), "CREATING\t1.36\thttps://eks.example.invalid"), "must be ACTIVE"),
            ("state", lambda f: f.state.pop(), "address count changed"),
            ("context", lambda f: f.read_values.__setitem__(("kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"), "https://wrong.example.invalid"), "does not point"),
            ("readyz", lambda f: f.read_values.__setitem__(("kubectl", "get", "--raw=/readyz"), "not ready"), "not ok"),
            ("namespace", lambda f: f.read_values.__setitem__(("kubectl", "get", "namespace", "argocd", "--ignore-not-found", "-o", "name"), "namespace/argocd"), "already exists"),
        )
        for name, mutate, message in cases:
            with self.subTest(name=name):
                fixture = Fixture()
                mutate(fixture)
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)

    def test_bootstrap_outputs_are_bound_to_account_and_vpc_shape(self) -> None:
        fixture = Fixture()

        def wrong_role(arguments: list[str]) -> str:
            if arguments[-1] == "karpenter_controller_role_arn":
                return "arn:aws:iam::999999999999:role/karpenter"
            return fixture.read_runner(arguments)

        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "reviewed AWS account"):
                MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, wrong_role)

        fixture = Fixture()

        def bad_vpc(arguments: list[str]) -> str:
            if arguments[-1] == "vpc_id":
                return "subnet-0123"
            return fixture.read_runner(arguments)

        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "VPC ID"):
                MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, bad_vpc)

    def test_execute_requires_separate_confirmation_before_any_read(self) -> None:
        bootstrap_calls: list[str] = []
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP"):
                MODULE.execute(
                    CONTROL_PLANE,
                    self.fixture.git_runner,
                    self.fixture.read_runner,
                    lambda account: bootstrap_calls.append(account) or 0,
                )
        self.assertEqual(self.fixture.read_calls, [])
        self.assertEqual(bootstrap_calls, [])

    def test_execute_invokes_bootstrap_once_and_stops_before_root(self) -> None:
        bootstrap_calls: list[str] = []
        environment = {
            **self.controls,
            "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP": MODULE.EXECUTION_CONFIRMATION,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            result = MODULE.execute(
                CONTROL_PLANE,
                self.fixture.git_runner,
                self.fixture.read_runner,
                lambda account: bootstrap_calls.append(account) or 0,
            )
        self.assertEqual(bootstrap_calls, [ACCOUNT])
        self.assertEqual(result["status"], "aws-dev-gitops-bootstrap-complete")
        self.assertEqual(result["argocd_version"], "v3.5.2")
        self.assertTrue(result["gitops_bootstrapped"])
        self.assertFalse(result["root_application_deployed"])
        self.assertFalse(result["runtime_qualified"])
        self.assertEqual(result["next_action"], "review-separate-root-application-deploy")

    def test_bootstrap_failure_is_not_retried_or_hidden(self) -> None:
        environment = {
            **self.controls,
            "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP": MODULE.EXECUTION_CONFIRMATION,
        }
        calls: list[str] = []
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(MODULE.CommandFailure, "preserve Terraform state"):
                MODULE.execute(
                    CONTROL_PLANE,
                    self.fixture.git_runner,
                    self.fixture.read_runner,
                    lambda account: calls.append(account) or 7,
                )
        self.assertEqual(calls, [ACCOUNT])


if __name__ == "__main__":
    unittest.main()
