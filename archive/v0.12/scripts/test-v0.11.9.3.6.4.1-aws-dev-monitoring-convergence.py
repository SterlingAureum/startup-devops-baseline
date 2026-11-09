#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.py"
SPEC = importlib.util.spec_from_file_location("aws_dev_monitoring_convergence", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev monitoring convergence executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONTROL_PLANE = "a" * 40
ACCOUNT = "123456789012"
EKS_ARN = f"arn:aws:eks:{MODULE.AWS_REGION}:{ACCOUNT}:cluster/{MODULE.CLUSTER_NAME}"


def application(name: str, path: str, *, health: str = "Healthy", revision: str = CONTROL_PLANE) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {
            "source": {
                "repoURL": "https://github.com/SterlingAureum/startup-devops-baseline.git",
                "targetRevision": "main",
                "path": path,
            }
        },
        "status": {
            "sync": {"status": "Synced", "revision": revision},
            "health": {"status": health},
        },
    }


def ready_workload(name: str) -> dict:
    return {
        "metadata": {"name": name, "generation": 1},
        "spec": {"replicas": 2},
        "status": {
            "observedGeneration": 1,
            "readyReplicas": 2,
            "updatedReplicas": 2,
            "availableReplicas": 2,
        },
    }


def demo_deployment() -> dict:
    value = ready_workload("demo-api")
    value["metadata"]["annotations"] = {
        "platform.startup.dev/release-id": MODULE.EXPECTED_RELEASE_ID,
        "platform.startup.dev/application-version": MODULE.EXPECTED_APPLICATION_VERSION,
        "platform.startup.dev/image-digest": MODULE.EXPECTED_IMAGE_DIGEST,
        "platform.startup.dev/source-commit": MODULE.EXPECTED_SOURCE_COMMIT,
    }
    return value


def postgres_cluster() -> dict:
    return {
        "metadata": {"name": "postgresql-baseline"},
        "status": {
            "instances": 3,
            "readyInstances": 3,
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }


def monitoring_application(health: str) -> dict:
    return {
        "metadata": {"name": MODULE.MONITORING_APPLICATION},
        "spec": {
            "source": {
                "chart": "kube-prometheus-stack",
                "targetRevision": MODULE.MONITORING_CHART_VERSION,
            }
        },
        "status": {"sync": {"status": "Synced"}, "health": {"status": health}},
    }


class Fixture:
    def __init__(self, *, converged: bool = False) -> None:
        self.git_values = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): CONTROL_PLANE,
            ("rev-parse", "origin/main"): CONTROL_PLANE,
            ("ls-remote", "origin", "refs/heads/main"): f"{CONTROL_PLANE}\trefs/heads/main",
        }
        self.root = application(MODULE.ROOT_APPLICATION, "clusters/aws/overlays/dev")
        self.demo_application = application(MODULE.DEMO_APPLICATION, "apps/demo-api/helm")
        self.demo = demo_deployment()
        self.postgres = postgres_cluster()
        self.monitoring = monitoring_application("Healthy" if converged else "Degraded")
        self.secret_name = f"secret/{MODULE.GRAFANA_SECRET}" if converged else ""
        self.grafana = ready_workload(MODULE.GRAFANA_DEPLOYMENT)
        if not converged:
            self.grafana["status"]["readyReplicas"] = 0
            self.grafana["status"]["availableReplicas"] = 0
        self.read_calls: list[tuple[str, ...]] = []

    def git_runner(self, arguments: list[str]) -> str:
        key = tuple(arguments)
        if key not in self.git_values:
            raise AssertionError(f"Unexpected git command: {key}")
        return self.git_values[key]

    def read_runner(self, arguments: list[str]) -> str:
        key = tuple(arguments)
        self.read_calls.append(key)
        if key == ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"):
            return ACCOUNT
        if key == (
            "aws", "eks", "describe-cluster", "--region", MODULE.AWS_REGION, "--name", MODULE.CLUSTER_NAME,
            "--query", "cluster.[status,version,arn]", "--output", "text",
        ):
            return f"ACTIVE\t1.36\t{EKS_ARN}"
        if key == ("kubectl", "config", "current-context"):
            return EKS_ARN
        if key == ("kubectl", "get", "--raw=/readyz"):
            return "ok"
        if key == ("kubectl", "-n", "argocd", "get", "application", MODULE.ROOT_APPLICATION, "-o", "json"):
            return json.dumps(self.root)
        if key == ("kubectl", "-n", "argocd", "get", "application", MODULE.DEMO_APPLICATION, "-o", "json"):
            return json.dumps(self.demo_application)
        if key == ("kubectl", "-n", "startup-apps", "get", "deployment", "demo-api", "-o", "json"):
            return json.dumps(self.demo)
        if key == ("kubectl", "-n", "data-platform", "get", "cluster", "postgresql-baseline", "-o", "json"):
            return json.dumps(self.postgres)
        if key == ("kubectl", "-n", "argocd", "get", "application", MODULE.MONITORING_APPLICATION, "-o", "json"):
            return json.dumps(self.monitoring)
        if key == (
            "kubectl", "-n", "observability", "get", "secret", MODULE.GRAFANA_SECRET,
            "--ignore-not-found", "-o", "name",
        ):
            return self.secret_name
        if key == (
            "kubectl", "-n", "observability", "get", "deployment", MODULE.GRAFANA_DEPLOYMENT, "-o", "json",
        ):
            return json.dumps(self.grafana)
        raise AssertionError(f"Unexpected command: {key}")

    def converge(self) -> None:
        self.secret_name = f"secret/{MODULE.GRAFANA_SECRET}"
        self.monitoring = monitoring_application("Healthy")
        self.grafana = ready_workload(MODULE.GRAFANA_DEPLOYMENT)


class AwsDevMonitoringConvergenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controls = {
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_DEV_MONITORING_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
        }

    def verify(self, fixture: Fixture) -> dict:
        with mock.patch.dict(os.environ, self.controls, clear=True):
            return MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)

    def test_verify_accepts_reviewed_missing_secret_state(self) -> None:
        fixture = Fixture()
        inventory = self.verify(fixture)
        result = MODULE.verification_result(inventory)
        self.assertEqual(result["status"], "aws-dev-monitoring-convergence-inputs-verified")
        self.assertEqual(result["convergence_state"], "missing-secret-repair-required")
        self.assertEqual(result["monitoring_application_status"], "Synced/Degraded")
        self.assertEqual(result["grafana_secret_status"], "absent")
        self.assertFalse(result["execution_authorized"])
        for private_key in ("aws_account_id", "cluster_arn", "secret_data"):
            self.assertNotIn(private_key, result)

    def test_verify_accepts_idempotent_already_converged_state(self) -> None:
        inventory = self.verify(Fixture(converged=True))
        self.assertEqual(inventory["convergence_state"], "already-converged")
        self.assertEqual(inventory["monitoring_application_status"], "Synced/Healthy")
        self.assertTrue(inventory["grafana_deployment_ready"])

    def test_confirmations_account_and_exact_main_are_required_before_live_reads(self) -> None:
        fixture = Fixture()
        with mock.patch.dict(os.environ, {"EXPECTED_AWS_ACCOUNT_ID": ACCOUNT}, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_MONITORING_PREFLIGHT"):
                MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner)
        self.assertEqual(fixture.read_calls, [])
        for key, value, message in (
            (("branch", "--show-current"), "feature/demo", "from main"),
            (("status", "--porcelain"), " M README.md", "clean worktree"),
            (("rev-parse", "HEAD"), "b" * 40, "HEAD"),
            (("rev-parse", "origin/main"), "b" * 40, "origin/main"),
            (("ls-remote", "origin", "refs/heads/main"), f"{'b' * 40}\trefs/heads/main", "Remote main"),
        ):
            with self.subTest(key=key):
                case = Fixture()
                case.git_values[key] = value
                with mock.patch.dict(os.environ, self.controls, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.verify_live_inputs(CONTROL_PLANE, case.git_runner, case.read_runner)
                self.assertEqual(case.read_calls, [])

    def test_cluster_app_demo_and_database_drift_fail_closed(self) -> None:
        cases = (
            ("context", lambda f: setattr(f, "read_runner", lambda args: "wrong" if args[:3] == ["kubectl", "config", "current-context"] else Fixture.read_runner(f, args)), "exact aws-dev EKS ARN"),
            ("root", lambda f: f.root["status"]["sync"].update(revision="b" * 40), "reviewed main"),
            ("demo-app", lambda f: f.demo_application["status"]["health"].update(status="Degraded"), "not Healthy"),
            ("demo-id", lambda f: f.demo["metadata"]["annotations"].update({"platform.startup.dev/release-id": "wrong"}), "release ID"),
            ("database", lambda f: f.postgres["status"].update(readyInstances=2), "not fully Ready"),
        )
        for name, mutate, message in cases:
            with self.subTest(name=name):
                fixture = Fixture()
                mutate(fixture)
                with self.assertRaisesRegex(ValueError, message):
                    self.verify(fixture)

    def test_unrelated_monitoring_failure_is_rejected(self) -> None:
        fixture = Fixture()
        fixture.secret_name = f"secret/{MODULE.GRAFANA_SECRET}"
        with self.assertRaisesRegex(ValueError, "reason other than"):
            self.verify(fixture)

    def test_execute_requires_separate_confirmation_before_any_read(self) -> None:
        fixture = Fixture()
        calls: list[str] = []
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_MONITORING_CONVERGENCE"):
                MODULE.execute(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, lambda account: calls.append(account) or 0)
        self.assertEqual(fixture.read_calls, [])
        self.assertEqual(calls, [])

    def test_execute_creates_secret_once_and_requires_final_convergence(self) -> None:
        fixture = Fixture()
        calls: list[str] = []

        def converge(account: str) -> int:
            calls.append(account)
            fixture.converge()
            return 0

        environment = {**self.controls, "CONFIRM_AWS_DEV_MONITORING_CONVERGENCE": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, environment, clear=True):
            result = MODULE.execute(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, converge)
        self.assertEqual(calls, [ACCOUNT])
        self.assertEqual(result["status"], "aws-dev-monitoring-convergence-complete")
        self.assertEqual(result["grafana_secret_action"], "created")
        self.assertTrue(result["monitoring_application_healthy"])
        self.assertFalse(result["runtime_qualified"])
        self.assertFalse(result["traffic_generated"])

    def test_execute_is_idempotent_when_already_converged(self) -> None:
        fixture = Fixture(converged=True)
        calls: list[str] = []
        environment = {**self.controls, "CONFIRM_AWS_DEV_MONITORING_CONVERGENCE": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, environment, clear=True):
            result = MODULE.execute(
                CONTROL_PLANE,
                fixture.git_runner,
                fixture.read_runner,
                lambda account: calls.append(account) or 0,
            )
        self.assertEqual(calls, [])
        self.assertEqual(result["grafana_secret_action"], "preserved")

    def test_failed_or_incomplete_convergence_is_not_hidden(self) -> None:
        environment = {**self.controls, "CONFIRM_AWS_DEV_MONITORING_CONVERGENCE": MODULE.EXECUTION_CONFIRMATION}
        fixture = Fixture()
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(MODULE.CommandFailure, "do not rerun"):
                MODULE.execute(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, lambda _account: 7)
        fixture = Fixture()
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "did not reach"):
                MODULE.execute(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, lambda _account: 0)


if __name__ == "__main__":
    unittest.main()
