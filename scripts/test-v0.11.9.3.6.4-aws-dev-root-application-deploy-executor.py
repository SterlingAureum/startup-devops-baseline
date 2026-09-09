#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.4-aws-dev-root-application-deploy.py"
SPEC = importlib.util.spec_from_file_location("aws_dev_root_deploy", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev Root deployment executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONTROL_PLANE = "a" * 40
ACCOUNT = "123456789012"
EKS_ENDPOINT = "https://eks.example.invalid"


def workload(name: str, image: str, kind: str = "Deployment") -> dict:
    return {
        "kind": kind,
        "metadata": {"name": name},
        "spec": {"template": {"spec": {"containers": [{"image": image}]}}},
        "status": {"replicas": 1, "readyReplicas": 1},
    }


def alb_application() -> dict:
    return {
        "metadata": {"name": MODULE.ALB_APPLICATION},
        "spec": {
            "source": {
                "chart": MODULE.ALB_APPLICATION,
                "targetRevision": MODULE.ALB_CHART_VERSION,
                "helm": {
                    "valuesObject": {
                        "clusterName": MODULE.CLUSTER_NAME,
                        "region": MODULE.AWS_REGION,
                        "vpcId": "vpc-0123abc",
                    }
                },
            },
            "destination": {"namespace": "kube-system"},
        },
        "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
    }


def root_application(revision: str = CONTROL_PLANE) -> dict:
    return {
        "metadata": {"name": MODULE.ROOT_APPLICATION},
        "spec": {
            "source": {
                "repoURL": "https://github.com/SterlingAureum/startup-devops-baseline.git",
                "targetRevision": "main",
                "path": "clusters/aws/overlays/dev",
            }
        },
        "status": {
            "sync": {"status": "Synced", "revision": revision},
            "health": {"status": "Healthy"},
        },
    }


class Fixture:
    def __init__(self) -> None:
        self.git_values = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): CONTROL_PLANE,
            ("rev-parse", "origin/main"): CONTROL_PLANE,
            ("ls-remote", "origin", "refs/heads/main"): f"{CONTROL_PLANE}\trefs/heads/main",
        }
        self.state = [f"module.fixture.resource[{index}]" for index in range(102)]
        self.state.append("module.eks.aws_eks_cluster.this[0]")
        self.outputs = {
            "vpc_id": "vpc-0123abc",
            "cnpg_backup_bucket_name": "startup-devops-backup-example",
            "cnpg_backup_role_arn": f"arn:aws:iam::{ACCOUNT}:role/cnpg-backup",
            "external_secrets_role_arn": f"arn:aws:iam::{ACCOUNT}:role/external-secrets",
            "external_secrets_secret_arn": f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:demo-api",
            "external_secrets_secret_name": "demo-api-postgresql",
            "route53_hosted_zone_id": "Z0123456789",
        }
        self.secret_arn = f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:demo-api"
        self.secret_name = "demo-api-postgresql"
        self.workloads = [
            workload(name, image, "StatefulSet" if name == "argocd-application-controller" else "Deployment")
            for name, image in MODULE.EXPECTED_ARGOCD_IMAGES.items()
        ]
        self.alb = alb_application()
        self.root: dict | None = None
        self.read_calls: list[tuple[str, ...]] = []

    def git_runner(self, arguments: list[str]) -> str:
        return self.git_values[tuple(arguments)]

    def read_runner(self, arguments: list[str]) -> str:
        key = tuple(str(value) for value in arguments)
        self.read_calls.append(key)
        if key[:2] == ("terraform", f"-chdir={MODULE.TF_DIR}"):
            if key[2:] == ("state", "list"):
                return "\n".join(self.state)
            return self.outputs[key[-1]]
        if key == ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"):
            return ACCOUNT
        if key == (
            "aws", "eks", "describe-cluster", "--region", "us-east-1", "--name",
            "startup-devops-baseline-dev", "--query", "cluster.[status,version,endpoint]", "--output", "text",
        ):
            return f"ACTIVE\t1.36\t{EKS_ENDPOINT}"
        if key == ("kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"):
            return EKS_ENDPOINT
        if key == ("kubectl", "get", "--raw=/readyz"):
            return "ok"
        if key[:4] == ("aws", "secretsmanager", "describe-secret", "--region"):
            return json.dumps({
                "ARN": self.secret_arn,
                "Name": self.secret_name,
                "DeletedDate": None,
            })
        if key[:3] == ("aws", "route53", "list-hosted-zones-by-name"):
            return json.dumps({
                "HostedZones": [{
                    "Id": "/hostedzone/Z0123456789",
                    "Name": "aureumstack.com.",
                    "Config": {"PrivateZone": False},
                }]
            })
        if key == ("kubectl", "-n", "argocd", "get", "deployments,statefulsets", "-o", "json"):
            return json.dumps({"items": self.workloads})
        if key == ("kubectl", "-n", "argocd", "get", "applications.argoproj.io", "-o", "json"):
            items = [self.alb]
            if self.root is not None:
                items.append(self.root)
            return json.dumps({"items": items})
        if key == ("kubectl", "-n", "argocd", "get", "application", MODULE.ALB_APPLICATION, "-o", "json"):
            return json.dumps(self.alb)
        if key == ("kubectl", "-n", "kube-system", "get", "deployment", MODULE.ALB_APPLICATION, "-o", "json"):
            return json.dumps({"status": {"replicas": 2, "readyReplicas": 2, "availableReplicas": 2}})
        if key == ("kubectl", "-n", "argocd", "get", "application", MODULE.ROOT_APPLICATION, "-o", "json"):
            if self.root is None:
                raise AssertionError("Root was queried before the mocked deployment")
            return json.dumps(self.root)
        raise AssertionError(f"Unexpected command: {key}")


class AwsDevRootDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.controls = {
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_DEV_ROOT_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
        }

    def verify(self):
        with mock.patch.dict(os.environ, self.controls, clear=True):
            return MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)

    def test_verify_accepts_exact_redacted_inventory(self) -> None:
        inventory = self.verify()
        result = MODULE.verification_result(inventory)
        self.assertEqual(result["status"], "aws-dev-root-deploy-inputs-verified")
        self.assertEqual(result["candidate_release_id"], MODULE.EXPECTED_RELEASE_ID)
        self.assertEqual(result["alb_application_status"], "Synced/Healthy")
        self.assertFalse(result["root_application_present"])
        self.assertFalse(result["execution_authorized"])
        for private_key in ("aws_account_id", "vpc_id", "secret_arn", "hosted_zone_id"):
            self.assertNotIn(private_key, result)
        self.assertEqual(len(self.fixture.read_calls), 18)

    def test_confirmations_and_account_format_are_required(self) -> None:
        with mock.patch.dict(os.environ, {"EXPECTED_AWS_ACCOUNT_ID": ACCOUNT}, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_ROOT_PREFLIGHT"):
                MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)
        with mock.patch.dict(
            os.environ,
            {"EXPECTED_AWS_ACCOUNT_ID": "redacted", "CONFIRM_AWS_DEV_ROOT_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "12-digit"):
                MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)

    def test_exact_local_and_remote_main_are_required_before_live_reads(self) -> None:
        cases = (
            (("branch", "--show-current"), "feature/demo", "from main"),
            (("status", "--porcelain"), " M README.md", "clean worktree"),
            (("rev-parse", "HEAD"), "b" * 40, "HEAD"),
            (("rev-parse", "origin/main"), "b" * 40, "origin/main"),
            (("ls-remote", "origin", "refs/heads/main"), f"{'b' * 40}\trefs/heads/main", "Remote main"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                fixture = Fixture()
                fixture.git_values[key] = value
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)
                self.assertEqual(fixture.read_calls, [])

    def test_root_and_release_content_identities_are_required(self) -> None:
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with mock.patch.object(MODULE, "ROOT_SOURCE_SHA256", "0" * 64):
                with self.assertRaisesRegex(ValueError, "Root source identity"):
                    MODULE.verify_live_inputs(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner)
        self.assertEqual(self.fixture.read_calls, [])

    def test_aws_cluster_state_and_context_fail_closed(self) -> None:
        cases = (
            ("account", lambda f: setattr(f, "read_runner", lambda args: "999999999999" if args[:2] == ["aws", "sts"] else Fixture.read_runner(f, args)), "caller account"),
            ("state", lambda f: f.state.pop(), "address count changed"),
            ("context", lambda f: setattr(f, "read_runner", lambda args: "https://wrong.invalid" if args[:3] == ["kubectl", "config", "view"] else Fixture.read_runner(f, args)), "does not point"),
        )
        for name, mutate, message in cases:
            with self.subTest(name=name):
                fixture = Fixture()
                mutate(fixture)
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)

    def test_secret_route53_argocd_and_root_absence_fail_closed(self) -> None:
        mutations = (
            ("secret", lambda f: f.outputs.__setitem__("external_secrets_secret_name", "unexpected"), "Secrets Manager name changed"),
            ("zone", lambda f: f.outputs.__setitem__("route53_hosted_zone_id", "ZOTHER"), "hosted-zone ID"),
            ("workload", lambda f: f.workloads[0]["status"].__setitem__("readyReplicas", 0), "not fully Ready"),
            ("alb", lambda f: f.alb["status"]["health"].__setitem__("status", "Degraded"), "not Healthy"),
            ("root", lambda f: setattr(f, "root", root_application()), "only the reviewed ALB"),
        )
        for name, mutate, message in mutations:
            with self.subTest(name=name):
                fixture = Fixture()
                mutate(fixture)
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)

    def test_execute_requires_separate_confirmation_before_any_read(self) -> None:
        calls: list[str] = []
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_ROOT_DEPLOY"):
                MODULE.execute(
                    CONTROL_PLANE,
                    self.fixture.git_runner,
                    self.fixture.read_runner,
                    lambda account: calls.append(account) or 0,
                )
        self.assertEqual(self.fixture.read_calls, [])
        self.assertEqual(calls, [])

    def test_execute_runs_once_and_requires_reviewed_root_revision(self) -> None:
        calls: list[str] = []

        def deploy(account: str) -> int:
            calls.append(account)
            self.fixture.root = root_application()
            return 0

        environment = {**self.controls, "CONFIRM_AWS_DEV_ROOT_DEPLOY": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, environment, clear=True):
            result = MODULE.execute(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner, deploy)
        self.assertEqual(calls, [ACCOUNT])
        self.assertEqual(result["status"], "aws-dev-root-application-deploy-complete")
        self.assertEqual(result["root_target_revision"], "main")
        self.assertEqual(result["root_resolved_revision"], CONTROL_PLANE)
        self.assertFalse(result["grafana_runtime_secret_prepared"])
        self.assertFalse(result["monitoring_converged"])
        self.assertFalse(result["runtime_qualified"])
        self.assertFalse(result["progressive_delivery_promoted"])
        self.assertEqual(result["next_action"], "review-separate-aws-dev-monitoring-convergence")

    def test_deploy_failure_is_not_retried_or_hidden(self) -> None:
        calls: list[str] = []
        environment = {**self.controls, "CONFIRM_AWS_DEV_ROOT_DEPLOY": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(MODULE.CommandFailure, "do not rerun"):
                MODULE.execute(
                    CONTROL_PLANE,
                    self.fixture.git_runner,
                    self.fixture.read_runner,
                    lambda account: calls.append(account) or 9,
                )
        self.assertEqual(calls, [ACCOUNT])

    def test_post_deploy_wrong_resolved_revision_is_rejected(self) -> None:
        def deploy(_account: str) -> int:
            self.fixture.root = root_application("b" * 40)
            return 0

        environment = {**self.controls, "CONFIRM_AWS_DEV_ROOT_DEPLOY": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "did not resolve"):
                MODULE.execute(CONTROL_PLANE, self.fixture.git_runner, self.fixture.read_runner, deploy)


if __name__ == "__main__":
    unittest.main()
