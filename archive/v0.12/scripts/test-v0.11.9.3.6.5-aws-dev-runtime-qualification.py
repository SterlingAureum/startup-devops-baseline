#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import unittest
from unittest import mock
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
SPEC = importlib.util.spec_from_file_location("aws_dev_runtime_qualification", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev runtime qualification executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONTROL_PLANE = "a" * 40
ACCOUNT = "123456789012"
NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
DEADLINE = (NOW + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
EKS_ARN = f"arn:aws:eks:{MODULE.AWS_REGION}:{ACCOUNT}:cluster/{MODULE.CLUSTER_NAME}"


def application(name: str, path: str) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"source": {"repoURL": "https://github.com/SterlingAureum/startup-devops-baseline.git", "targetRevision": "main", "path": path}},
        "status": {"sync": {"status": "Synced", "revision": CONTROL_PLANE}, "health": {"status": "Healthy"}},
    }


def ready_workload(name: str) -> dict:
    return {
        "metadata": {"name": name, "generation": 1},
        "spec": {"replicas": 2},
        "status": {"observedGeneration": 1, "readyReplicas": 2, "updatedReplicas": 2, "availableReplicas": 2},
    }


def query(value: str) -> str:
    return json.dumps({"status": "success", "data": {"result": [{"value": [1, value]}]}})


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeProcess:
    def __init__(self, stubborn: bool = False) -> None:
        self.returncode: int | None = None
        self.stubborn = stubborn
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: int) -> int:
        self.wait_calls.append(timeout)
        if self.stubborn and self.kill_calls == 0:
            raise MODULE.subprocess.TimeoutExpired("kubectl", timeout)
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class Fixture:
    def __init__(self) -> None:
        self.git_values = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): CONTROL_PLANE,
            ("rev-parse", "origin/main"): CONTROL_PLANE,
            ("ls-remote", "origin", "refs/heads/main"): f"{CONTROL_PLANE}\trefs/heads/main",
        }
        self.root = application(MODULE.ROOT_APPLICATION, "clusters/aws/overlays/dev")
        self.demo_app = application(MODULE.DEMO_APPLICATION, "apps/demo-api/helm")
        self.monitoring = {
            "metadata": {"name": MODULE.MONITORING_APPLICATION},
            "spec": {"source": {"chart": "kube-prometheus-stack", "targetRevision": MODULE.MONITORING_CHART_VERSION}},
            "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
        }
        self.demo = ready_workload("demo-api")
        self.demo["metadata"]["annotations"] = {
            "platform.startup.dev/environment": "aws-dev",
            "platform.startup.dev/release-id": MODULE.EXPECTED_RELEASE_ID,
            "platform.startup.dev/application-version": MODULE.EXPECTED_APPLICATION_VERSION,
            "platform.startup.dev/image-digest": MODULE.EXPECTED_IMAGE_DIGEST,
            "platform.startup.dev/source-commit": MODULE.EXPECTED_SOURCE_COMMIT,
        }
        self.pods = {"items": [{
            "metadata": {"name": "demo-api-1"},
            "spec": {"containers": [{"name": "demo-api", "image": MODULE.EXPECTED_IMAGE}]},
            "status": {"phase": "Running", "containerStatuses": [{"name": "demo-api", "ready": True, "imageID": f"docker-pullable://demo@{MODULE.EXPECTED_IMAGE_DIGEST}"}]},
        }]}
        self.postgres = {"status": {"instances": 3, "readyInstances": 3, "conditions": [{"type": "Ready", "status": "True"}]}}
        self.grafana = ready_workload(MODULE.GRAFANA_DEPLOYMENT)
        self.request_rate = "0.25"
        self.availability = "1"
        self.latency = "0.999"
        self.critical_alerts: list[dict] = []
        self.read_calls: list[tuple[str, ...]] = []
        self.prometheus_calls: list[str] = []

    def git_runner(self, arguments: list[str]) -> str:
        key = tuple(arguments)
        if key not in self.git_values:
            raise AssertionError(f"Unexpected git command: {key}")
        return self.git_values[key]

    def read_runner(self, arguments: list[str]) -> str:
        key = tuple(arguments)
        self.read_calls.append(key)
        direct: dict[tuple[str, ...], str] = {
            ("aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"): ACCOUNT,
            ("aws", "eks", "describe-cluster", "--region", MODULE.AWS_REGION, "--name", MODULE.CLUSTER_NAME, "--query", "cluster.[status,version,arn]", "--output", "text"): f"ACTIVE\t1.36\t{EKS_ARN}",
            ("kubectl", "config", "current-context"): EKS_ARN,
            ("kubectl", "get", "--raw=/readyz"): "ok",
            ("kubectl", "-n", "argocd", "get", "application", MODULE.ROOT_APPLICATION, "-o", "json"): json.dumps(self.root),
            ("kubectl", "-n", "argocd", "get", "application", MODULE.DEMO_APPLICATION, "-o", "json"): json.dumps(self.demo_app),
            ("kubectl", "-n", "argocd", "get", "application", MODULE.MONITORING_APPLICATION, "-o", "json"): json.dumps(self.monitoring),
            ("kubectl", "-n", "startup-apps", "get", "deployment", "demo-api", "-o", "json"): json.dumps(self.demo),
            ("kubectl", "-n", "startup-apps", "get", "pods", "-l", "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api", "-o", "json"): json.dumps(self.pods),
            ("kubectl", "-n", "data-platform", "get", "cluster", "postgresql-baseline", "-o", "json"): json.dumps(self.postgres),
            ("kubectl", "-n", "observability", "get", "secret", MODULE.GRAFANA_SECRET, "--ignore-not-found", "-o", "name"): f"secret/{MODULE.GRAFANA_SECRET}",
            ("kubectl", "-n", "observability", "get", "deployment", MODULE.GRAFANA_DEPLOYMENT, "-o", "json"): json.dumps(self.grafana),
        }
        if key in direct:
            return direct[key]
        raise AssertionError(f"Unexpected command: {key}")

    def prometheus_reader(self, suffix: str) -> str:
        self.prometheus_calls.append(suffix)
        if suffix == "/api/v1/targets?state=active":
            return json.dumps({"data": {"activeTargets": [{"labels": {"job": "demo-api"}, "health": "up"}]}})
        if suffix == "/api/v1/rules":
            names = [
                "demo_api:slo_http_requests:rate30d",
                "demo_api:slo_availability:ratio30d",
                "demo_api:slo_latency:ratio30d",
                "DemoApiAvailabilityErrorBudgetFastBurn",
                "DemoApiLatencyErrorBudgetFastBurn",
            ]
            return json.dumps({"data": {"groups": [{"rules": [{"name": name} for name in names]}]}})
        if "slo_http_requests" in suffix:
            return query(self.request_rate)
        if "slo_availability" in suffix:
            return query(self.availability)
        if "slo_latency" in suffix:
            return query(self.latency)
        if "ALERTS" in suffix:
            return json.dumps({"status": "success", "data": {"result": self.critical_alerts}})
        raise AssertionError(f"Unexpected Prometheus request: {suffix}")


class AwsDevRuntimeQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controls = {
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "AWS_DEV_RUNTIME_QUALIFICATION_END_UTC": DEADLINE,
            "CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION_PREFLIGHT": MODULE.OBSERVATION_CONFIRMATION,
        }

    def verify(self, fixture: Fixture) -> dict:
        with mock.patch.dict(os.environ, self.controls, clear=True):
            return MODULE.verify_live_inputs(
                CONTROL_PLANE,
                fixture.git_runner,
                fixture.read_runner,
                NOW,
                fixture.prometheus_reader,
            )

    def test_preflight_is_read_only_and_reports_not_authorized(self) -> None:
        result = MODULE.verification_result(self.verify(Fixture()))
        self.assertEqual(result["status"], "aws-dev-runtime-qualification-inputs-verified")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["traffic_generated"])
        self.assertFalse(result["runtime_qualified"])
        self.assertEqual(result["remaining_window_seconds"], 7200)
        for private in ("aws_account_id", "cluster_arn", "secret_data"):
            self.assertNotIn(private, result)

    def test_confirmation_deadline_and_exact_main_fail_before_live_reads(self) -> None:
        fixture = Fixture()
        with mock.patch.dict(os.environ, {"EXPECTED_AWS_ACCOUNT_ID": ACCOUNT, "AWS_DEV_RUNTIME_QUALIFICATION_END_UTC": DEADLINE}, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION_PREFLIGHT"):
                MODULE.verify_live_inputs(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, NOW)
        self.assertEqual(fixture.read_calls, [])
        for deadline, message in (
            ((NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"), "15 minutes"),
            ((NOW + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ"), "eight hours"),
        ):
            case = Fixture()
            controls = {**self.controls, "AWS_DEV_RUNTIME_QUALIFICATION_END_UTC": deadline}
            with mock.patch.dict(os.environ, controls, clear=True):
                with self.assertRaisesRegex(ValueError, message):
                    MODULE.verify_live_inputs(CONTROL_PLANE, case.git_runner, case.read_runner, NOW)
            self.assertEqual(case.read_calls, [])
        case = Fixture()
        case.git_values[("status", "--porcelain")] = " M README.md"
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "clean worktree"):
                MODULE.verify_live_inputs(CONTROL_PLANE, case.git_runner, case.read_runner, NOW)
        self.assertEqual(case.read_calls, [])

    def test_runtime_identity_and_health_drift_fail_closed(self) -> None:
        cases = (
            (lambda f: f.root["status"]["sync"].update(revision="b" * 40), "reviewed main"),
            (lambda f: f.monitoring["status"]["health"].update(status="Degraded"), "not Healthy"),
            (lambda f: f.demo["metadata"]["annotations"].update({"platform.startup.dev/release-id": "wrong"}), "immutable identity"),
            (lambda f: f.pods["items"][0]["status"]["containerStatuses"][0].update(ready=False), "not Running and ready"),
            (lambda f: f.postgres["status"].update(readyInstances=2), "not fully Ready"),
        )
        for mutate, message in cases:
            fixture = Fixture()
            mutate(fixture)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.verify(fixture)

    def test_execute_requires_separate_confirmation_before_reads_or_traffic(self) -> None:
        fixture = Fixture()
        traffic: list[str] = []
        with mock.patch.dict(os.environ, self.controls, clear=True):
            with self.assertRaisesRegex(ValueError, "CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION"):
                MODULE.execute(CONTROL_PLANE, fixture.git_runner, fixture.read_runner, lambda host: traffic.append(host) or {}, NOW)
        self.assertEqual(fixture.read_calls, [])
        self.assertEqual(traffic, [])

    def test_default_traffic_generator_is_bounded_and_validates_responses(self) -> None:
        responses = {
            "health": json.dumps({"status": "ok"}),
            "ready": json.dumps({"status": "ready", "database": "ok"}),
            "version": json.dumps({"environment": "aws-dev", "version": MODULE.EXPECTED_APPLICATION_VERSION}),
        }
        calls: list[str] = []
        sleeps: list[float] = []

        def command(arguments: list[str]) -> str:
            path = arguments[-1].rsplit("/", 1)[-1]
            calls.append(path)
            return responses[path]

        with mock.patch.object(MODULE, "run_command", command):
            result = MODULE.generate_bounded_traffic(MODULE.PUBLIC_HOSTNAME, sleeps.append)
        self.assertEqual(result["request_count"], 54)
        self.assertEqual(calls.count("health"), 18)
        self.assertEqual(calls.count("ready"), 18)
        self.assertEqual(calls.count("version"), 18)
        self.assertEqual(sleeps.count(2), 18)
        self.assertEqual(sleeps[12], 40)
        self.assertEqual(sleeps[-1], 35)

    def test_execute_generates_one_bounded_batch_and_accepts_slo(self) -> None:
        fixture = Fixture()
        traffic: list[str] = []
        controls = {**self.controls, "CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION": MODULE.EXECUTION_CONFIRMATION}
        with mock.patch.dict(os.environ, controls, clear=True):
            result = MODULE.execute(
                CONTROL_PLANE,
                fixture.git_runner,
                fixture.read_runner,
                lambda host: traffic.append(host) or {"request_count": 54},
                NOW,
                fixture.prometheus_reader,
            )
        self.assertEqual(traffic, [MODULE.PUBLIC_HOSTNAME])
        self.assertEqual(result["status"], "aws-dev-runtime-qualification-complete")
        self.assertEqual(result["bounded_request_count"], 54)
        self.assertTrue(result["runtime_qualified"])
        self.assertTrue(result["traffic_generated"])
        self.assertFalse(result["progressive_delivery_promoted"])
        self.assertFalse(result["automatic_teardown_executed"])

    def test_slo_or_alert_failure_stops_after_bounded_traffic(self) -> None:
        controls = {**self.controls, "CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION": MODULE.EXECUTION_CONFIRMATION}
        for mutate, message in (
            (lambda f: setattr(f, "request_rate", "0"), "request series"),
            (lambda f: setattr(f, "availability", "0.998"), "availability SLO"),
            (lambda f: setattr(f, "latency", "0.98"), "latency SLO"),
            (lambda f: setattr(f, "critical_alerts", [{"metric": {"alertname": "DemoApiCritical"}}]), "critical aws-dev alert"),
        ):
            fixture = Fixture()
            mutate(fixture)
            with mock.patch.dict(os.environ, controls, clear=True):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    MODULE.execute(
                        CONTROL_PLANE,
                        fixture.git_runner,
                        fixture.read_runner,
                        lambda _host: {"request_count": 54},
                        NOW,
                        fixture.prometheus_reader,
                    )

    def test_port_forward_is_loopback_only_secure_and_cleaned_after_success(self) -> None:
        process = FakeProcess()
        opened: list[tuple[str, int]] = []

        def fake_urlopen(url: str, timeout: int) -> FakeResponse:
            opened.append((url, timeout))
            if url.endswith("/-/ready"):
                return FakeResponse("Prometheus Server is Ready.")
            return FakeResponse('{"status":"success"}')

        def fake_popen(arguments: list[str], **kwargs: object) -> FakeProcess:
            self.assertEqual(arguments, [
                "kubectl", "-n", "observability", "port-forward",
                "--address", "127.0.0.1",
                f"service/{MODULE.PROMETHEUS_SERVICE}",
                "19090:9090",
            ])
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(
                stat.S_IMODE(os.fstat(kwargs["stdout"].fileno()).st_mode),
                0o600,
            )
            return process

        with (
            mock.patch.object(MODULE, "free_loopback_port", return_value=19090),
            mock.patch.object(MODULE.subprocess, "Popen", side_effect=fake_popen),
            mock.patch.object(MODULE, "urlopen", side_effect=fake_urlopen),
        ):
            with MODULE.prometheus_port_forward() as reader:
                self.assertEqual(json.loads(reader("/api/v1/rules"))["status"], "success")

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 0)
        self.assertEqual(opened, [
            ("http://127.0.0.1:19090/-/ready", MODULE.PROMETHEUS_FORWARD_PROBE_SECONDS),
            ("http://127.0.0.1:19090/api/v1/rules", MODULE.PROMETHEUS_REQUEST_TIMEOUT_SECONDS),
        ])

    def test_port_forward_is_cleaned_on_interrupt_and_forcibly_killed_if_needed(self) -> None:
        process = FakeProcess(stubborn=True)
        with (
            mock.patch.object(MODULE, "free_loopback_port", return_value=19091),
            mock.patch.object(MODULE.subprocess, "Popen", return_value=process),
            mock.patch.object(MODULE, "urlopen", return_value=FakeResponse("Prometheus Server is Ready.")),
        ):
            with self.assertRaises(KeyboardInterrupt):
                with MODULE.prometheus_port_forward():
                    raise KeyboardInterrupt

        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 1)

    def test_port_forward_readiness_timeout_fails_closed_and_cleans_up(self) -> None:
        process = FakeProcess()
        with (
            mock.patch.object(MODULE, "free_loopback_port", return_value=19092),
            mock.patch.object(MODULE.subprocess, "Popen", return_value=process),
            mock.patch.object(MODULE, "urlopen", side_effect=URLError("connection refused")),
            mock.patch.object(
                MODULE.time,
                "monotonic",
                side_effect=[0, MODULE.PROMETHEUS_FORWARD_READY_SECONDS + 1],
            ),
        ):
            with self.assertRaisesRegex(MODULE.CommandFailure, "readiness timed out") as stopped:
                with MODULE.prometheus_port_forward():
                    self.fail("Unreachable port-forward must not yield a reader")

        self.assertIn("last probe: Prometheus request failed", str(stopped.exception))
        self.assertIn("connection refused", str(stopped.exception))
        self.assertEqual(process.terminate_calls, 1)
        self.assertEqual(process.kill_calls, 0)

    def test_port_forward_accepts_readiness_needing_more_than_one_second(self) -> None:
        process = FakeProcess()
        observed_timeouts: list[int] = []

        def delayed_readiness(_url: str, timeout: int) -> FakeResponse:
            observed_timeouts.append(timeout)
            if timeout <= 1:
                raise TimeoutError("simulated response exceeds one second")
            return FakeResponse("Prometheus Server is Ready.")

        with (
            mock.patch.object(MODULE, "free_loopback_port", return_value=19093),
            mock.patch.object(MODULE.subprocess, "Popen", return_value=process),
            mock.patch.object(MODULE, "urlopen", side_effect=delayed_readiness),
        ):
            with MODULE.prometheus_port_forward():
                pass

        self.assertEqual(observed_timeouts, [MODULE.PROMETHEUS_FORWARD_PROBE_SECONDS])
        self.assertGreater(MODULE.PROMETHEUS_FORWARD_PROBE_SECONDS, 1)
        self.assertEqual(process.terminate_calls, 1)

    def test_cli_interrupt_reports_exit_130_after_context_cleanup(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch("sys.argv", [str(EXECUTOR), "verify", "--expected-control-plane-commit", CONTROL_PLANE]),
            mock.patch.object(MODULE, "verify_live_inputs", side_effect=KeyboardInterrupt),
            mock.patch("sys.stderr", stderr),
        ):
            with self.assertRaises(SystemExit) as stopped:
                MODULE.main()

        self.assertEqual(stopped.exception.code, 130)
        self.assertIn("Prometheus port-forward cleaned up", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
