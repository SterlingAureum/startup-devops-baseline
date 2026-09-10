#!/usr/bin/env python3
"""Verify or execute the reviewed aws-dev runtime qualification."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
AWS_DEV_RELEASE = ROOT / "apps/demo-api/helm/values/releases/aws-dev.yaml"
AWS_DEV_RELEASE_SHA256 = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
ROOT_APPLICATION = "startup-devops-aws-dev-root"
DEMO_APPLICATION = "demo-api-aws-dev"
MONITORING_APPLICATION = "monitoring-aws-dev"
MONITORING_CHART_VERSION = "88.5.0"
GRAFANA_SECRET = "observability-grafana-admin"
GRAFANA_DEPLOYMENT = "observability-metrics-grafana"
EXPECTED_RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"
EXPECTED_APPLICATION_VERSION = "sha-cf0a6bc"
EXPECTED_IMAGE_REPOSITORY = "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api"
EXPECTED_IMAGE_DIGEST = "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623"
EXPECTED_SOURCE_COMMIT = "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
EXPECTED_IMAGE = f"{EXPECTED_IMAGE_REPOSITORY}@{EXPECTED_IMAGE_DIGEST}"
PUBLIC_HOSTNAME = "demo.dev.aureumstack.com"
PROMETHEUS_SERVICE = "observability-metrics-prometheus"
PROMETHEUS_REMOTE_PORT = 9090
OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-runtime-qualification"
EXECUTION_CONFIRMATION = "qualify-reviewed-aws-dev-runtime"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MINIMUM_REMAINING_SECONDS = 15 * 60
MAXIMUM_WINDOW_SECONDS = 8 * 60 * 60
WARMUP_ROUNDS = 12
FINAL_ROUNDS = 6
REQUESTS_PER_ROUND = 3
PROMETHEUS_FORWARD_READY_SECONDS = 30
PROMETHEUS_FORWARD_PROBE_SECONDS = 1
PROMETHEUS_REQUEST_TIMEOUT_SECONDS = 20
PROMETHEUS_FORWARD_STOP_SECONDS = 5


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
ReadRunner = Callable[[list[str]], str]
TrafficRunner = Callable[[str], dict[str, Any]]
SleepRunner = Callable[[float], None]
PrometheusReader = Callable[[str], str]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run_command(arguments: list[str]) -> str:
    result = subprocess.run(arguments, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"{arguments[0]} command failed"
        raise CommandFailure(detail)
    return result.stdout.strip()


def run_git(arguments: list[str]) -> str:
    return run_command(["git", "-C", str(ROOT), *arguments])


def free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def read_forward_log(log_file: Any) -> str:
    log_file.flush()
    position = log_file.tell()
    log_file.seek(0)
    detail = log_file.read().strip()
    log_file.seek(position)
    return detail[-2000:]


def stop_port_forward(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=PROMETHEUS_FORWARD_STOP_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROMETHEUS_FORWARD_STOP_SECONDS)


def read_loopback_url(url: str, timeout: int) -> str:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback-only transport
            return response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise CommandFailure(f"Prometheus request failed: {error}") from error


@contextmanager
def prometheus_port_forward() -> Iterator[PrometheusReader]:
    local_port = free_loopback_port()
    base_url = f"http://127.0.0.1:{local_port}"
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                "kubectl", "-n", "observability", "port-forward",
                "--address", "127.0.0.1",
                f"service/{PROMETHEUS_SERVICE}",
                f"{local_port}:{PROMETHEUS_REMOTE_PORT}",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + PROMETHEUS_FORWARD_READY_SECONDS
            while True:
                if process.poll() is not None:
                    detail = read_forward_log(log_file) or "kubectl port-forward exited without output"
                    raise CommandFailure(f"Prometheus port-forward exited before readiness: {detail}")
                try:
                    ready = read_loopback_url(
                        f"{base_url}/-/ready",
                        PROMETHEUS_FORWARD_PROBE_SECONDS,
                    )
                    if "Ready" in ready:
                        break
                except CommandFailure:
                    pass
                if time.monotonic() >= deadline:
                    detail = read_forward_log(log_file) or "no kubectl port-forward output"
                    raise CommandFailure(f"Prometheus port-forward readiness timed out: {detail}")
                time.sleep(1)

            def read_prometheus(suffix: str) -> str:
                return read_loopback_url(
                    f"{base_url}{suffix}",
                    PROMETHEUS_REQUEST_TIMEOUT_SECONDS,
                )

            yield read_prometheus
        finally:
            stop_port_forward(process)


def parse_json(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} returned malformed JSON") from error
    require(isinstance(value, dict), f"{label} must return a JSON object")
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_deadline(now: datetime) -> tuple[str, int]:
    raw = os.environ.get("AWS_DEV_RUNTIME_QUALIFICATION_END_UTC", "")
    try:
        deadline = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError("AWS_DEV_RUNTIME_QUALIFICATION_END_UTC must use YYYY-MM-DDTHH:MM:SSZ") from error
    remaining = int((deadline - now).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Runtime qualification requires at least 15 minutes remaining")
    require(remaining <= MAXIMUM_WINDOW_SECONDS, "Runtime qualification deadline must be within eight hours")
    return raw, remaining


def validate_exact_main(expected_commit: str, git_runner: GitRunner) -> None:
    require(bool(COMMIT_RE.fullmatch(expected_commit)), "Expected control-plane commit must be 40 lowercase hex characters")
    require(git_runner(["branch", "--show-current"]) == "main", "Runtime qualification must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Runtime qualification requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_commit, "HEAD does not equal the reviewed commit")
    require(git_runner(["rev-parse", "origin/main"]) == expected_commit, "origin/main does not equal the reviewed commit")
    remote = git_runner(["ls-remote", "origin", "refs/heads/main"]).splitlines()
    require(remote == [f"{expected_commit}\trefs/heads/main"], "Remote main does not equal the reviewed commit")


def require_application(application: dict[str, Any], name: str, expected_commit: str, path: str) -> None:
    source = application.get("spec", {}).get("source", {})
    require(application.get("metadata", {}).get("name") == name, f"{name} identity changed")
    require(source.get("repoURL") == "https://github.com/SterlingAureum/startup-devops-baseline.git", f"{name} repository changed")
    require(source.get("targetRevision") == "main", f"{name} targetRevision must remain main")
    require(source.get("path") == path, f"{name} source path changed")
    require(application.get("status", {}).get("sync", {}).get("status") == "Synced", f"{name} is not Synced")
    require(application.get("status", {}).get("health", {}).get("status") == "Healthy", f"{name} is not Healthy")
    require(application.get("status", {}).get("sync", {}).get("revision") == expected_commit, f"{name} did not resolve reviewed main")


def workload_is_ready(workload: dict[str, Any]) -> bool:
    replicas = workload.get("spec", {}).get("replicas")
    status = workload.get("status", {})
    return (
        isinstance(replicas, int)
        and replicas > 0
        and status.get("observedGeneration") == workload.get("metadata", {}).get("generation")
        and status.get("readyReplicas") == replicas
        and status.get("updatedReplicas") == replicas
        and status.get("availableReplicas") == replicas
    )


def prometheus_read(prometheus_reader: PrometheusReader, suffix: str) -> dict[str, Any]:
    return parse_json(prometheus_reader(suffix), f"Prometheus {suffix}")


def query_prometheus(prometheus_reader: PrometheusReader, expression: str) -> dict[str, Any]:
    return prometheus_read(prometheus_reader, f"/api/v1/query?query={quote(expression, safe='')}")


def scalar_query(prometheus_reader: PrometheusReader, expression: str, label: str) -> float:
    payload = query_prometheus(prometheus_reader, expression)
    require(payload.get("status") == "success", f"{label} query failed")
    result = payload.get("data", {}).get("result", [])
    require(len(result) == 1, f"{label} query must return exactly one series")
    try:
        return float(result[0]["value"][1])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{label} query returned a non-numeric value") from error


def read_live_state(
    expected_commit: str,
    read_runner: ReadRunner,
    prometheus_reader: PrometheusReader | None = None,
) -> dict[str, Any]:
    expected_account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    require(bool(ACCOUNT_RE.fullmatch(expected_account)), "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    actual_account = read_runner(["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    require(actual_account == expected_account, "AWS caller account does not match EXPECTED_AWS_ACCOUNT_ID")
    cluster = read_runner([
        "aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME,
        "--query", "cluster.[status,version,arn]", "--output", "text",
    ]).split()
    require(len(cluster) == 3 and cluster[0] == "ACTIVE", "aws-dev EKS cluster must be ACTIVE")
    require(read_runner(["kubectl", "config", "current-context"]) == cluster[2], "kubectl context is not the exact aws-dev EKS ARN")
    require(read_runner(["kubectl", "get", "--raw=/readyz"]) == "ok", "Kubernetes /readyz is not ok")

    root = parse_json(read_runner(["kubectl", "-n", "argocd", "get", "application", ROOT_APPLICATION, "-o", "json"]), "Root Application")
    require_application(root, ROOT_APPLICATION, expected_commit, "clusters/aws/overlays/dev")
    demo_app = parse_json(read_runner(["kubectl", "-n", "argocd", "get", "application", DEMO_APPLICATION, "-o", "json"]), "demo-api Application")
    require_application(demo_app, DEMO_APPLICATION, expected_commit, "apps/demo-api/helm")

    monitoring = parse_json(read_runner(["kubectl", "-n", "argocd", "get", "application", MONITORING_APPLICATION, "-o", "json"]), "monitoring Application")
    source = monitoring.get("spec", {}).get("source", {})
    require(source.get("chart") == "kube-prometheus-stack", "monitoring chart changed")
    require(source.get("targetRevision") == MONITORING_CHART_VERSION, "monitoring chart version changed")
    require(monitoring.get("status", {}).get("sync", {}).get("status") == "Synced", "monitoring Application is not Synced")
    require(monitoring.get("status", {}).get("health", {}).get("status") == "Healthy", "monitoring Application is not Healthy")

    demo = parse_json(read_runner(["kubectl", "-n", "startup-apps", "get", "deployment", "demo-api", "-o", "json"]), "demo-api Deployment")
    require(workload_is_ready(demo), "demo-api Deployment is not fully Ready")
    annotations = demo.get("metadata", {}).get("annotations", {})
    expected_annotations = {
        "platform.startup.dev/environment": "aws-dev",
        "platform.startup.dev/release-id": EXPECTED_RELEASE_ID,
        "platform.startup.dev/application-version": EXPECTED_APPLICATION_VERSION,
        "platform.startup.dev/image-digest": EXPECTED_IMAGE_DIGEST,
        "platform.startup.dev/source-commit": EXPECTED_SOURCE_COMMIT,
    }
    require(all(annotations.get(key) == value for key, value in expected_annotations.items()), "demo-api immutable identity changed")

    pods = parse_json(read_runner(["kubectl", "-n", "startup-apps", "get", "pods", "-l", "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api", "-o", "json"]), "demo-api Pods")
    pod_items = pods.get("items", [])
    require(bool(pod_items), "demo-api has no selected Pods")
    for pod in pod_items:
        statuses = pod.get("status", {}).get("containerStatuses", [])
        containers = pod.get("spec", {}).get("containers", [])
        require(pod.get("status", {}).get("phase") == "Running" and statuses and all(item.get("ready") is True for item in statuses), "demo-api Pod is not Running and ready")
        require(containers and all(item.get("image") == EXPECTED_IMAGE for item in containers), "demo-api Pod image changed")
        require(all(item.get("imageID", "").endswith(f"@{EXPECTED_IMAGE_DIGEST}") for item in statuses), "demo-api Pod imageID digest changed")

    postgres = parse_json(read_runner(["kubectl", "-n", "data-platform", "get", "cluster", "postgresql-baseline", "-o", "json"]), "CloudNativePG Cluster")
    instances = postgres.get("status", {}).get("instances", 0)
    conditions = postgres.get("status", {}).get("conditions", [])
    require(instances > 0 and postgres.get("status", {}).get("readyInstances") == instances and any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions), "CloudNativePG Cluster is not fully Ready")

    secret_name = read_runner(["kubectl", "-n", "observability", "get", "secret", GRAFANA_SECRET, "--ignore-not-found", "-o", "name"])
    require(secret_name == f"secret/{GRAFANA_SECRET}", "independent Grafana Secret is absent")
    grafana = parse_json(read_runner(["kubectl", "-n", "observability", "get", "deployment", GRAFANA_DEPLOYMENT, "-o", "json"]), "Grafana Deployment")
    require(workload_is_ready(grafana), "Grafana Deployment is not fully Ready")

    def validate_prometheus(reader: PrometheusReader) -> None:
        targets = prometheus_read(reader, "/api/v1/targets?state=active")
        active = targets.get("data", {}).get("activeTargets", [])
        require(any(item.get("labels", {}).get("job") == "demo-api" and item.get("health") == "up" for item in active), "demo-api Prometheus target is not up")
        rules = prometheus_read(reader, "/api/v1/rules")
        names = {item.get("name") for group in rules.get("data", {}).get("groups", []) for item in group.get("rules", [])}
        required_rules = {
            "demo_api:slo_http_requests:rate30d",
            "demo_api:slo_availability:ratio30d",
            "demo_api:slo_latency:ratio30d",
            "DemoApiAvailabilityErrorBudgetFastBurn",
            "DemoApiLatencyErrorBudgetFastBurn",
        }
        require(required_rules <= names, "required demo-api SLO rule inventory changed")

    if prometheus_reader is None:
        with prometheus_port_forward() as session_reader:
            validate_prometheus(session_reader)
    else:
        validate_prometheus(prometheus_reader)
    return {
        "control_plane_commit": expected_commit,
        "cluster_status": cluster[0],
        "cluster_version": cluster[1],
        "kubernetes_readyz": "ok",
        "root_application_status": "Synced/Healthy",
        "demo_application_status": "Synced/Healthy",
        "monitoring_application_status": "Synced/Healthy",
        "demo_deployment_ready": True,
        "database_ready": True,
        "grafana_deployment_ready": True,
        "prometheus_demo_target_up": True,
        "candidate_release_id": EXPECTED_RELEASE_ID,
    }


def verify_live_inputs(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_command,
    now: datetime | None = None,
    prometheus_reader: PrometheusReader | None = None,
) -> dict[str, Any]:
    require(os.environ.get("CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION_PREFLIGHT") == OBSERVATION_CONFIRMATION, f"Set CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION_PREFLIGHT={OBSERVATION_CONFIRMATION}")
    current_time = now or datetime.now(timezone.utc)
    deadline, remaining = parse_deadline(current_time)
    validate_exact_main(expected_commit, git_runner)
    require(file_sha256(AWS_DEV_RELEASE) == AWS_DEV_RELEASE_SHA256, "aws-dev release identity changed")
    state = read_live_state(expected_commit, read_runner, prometheus_reader)
    return {**state, "qualification_end_utc": deadline, "remaining_window_seconds": remaining}


def verification_result(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-runtime-qualification-inputs-verified",
        **inventory,
        "execution_authorized": False,
        "traffic_generated": False,
        "runtime_qualified": False,
        "read_only_checks": [
            "clean-exact-remote-main",
            "reviewed-time-window",
            "aws-caller-and-exact-eks-context",
            "root-demo-and-monitoring-health",
            "demo-immutable-image-and-pod-identity",
            "database-and-grafana-readiness",
            "prometheus-target-and-slo-rule-inventory",
        ],
        "next_action": "obtain-separate-aws-dev-runtime-qualification-approval",
    }


def generate_bounded_traffic(hostname: str, sleep_runner: SleepRunner = time.sleep) -> dict[str, Any]:
    requests = 0
    for rounds, final_wait in ((WARMUP_ROUNDS, 40), (FINAL_ROUNDS, 35)):
        for _ in range(rounds):
            for path in ("health", "ready", "version"):
                payload = parse_json(
                    run_command(["curl", "--fail", "--silent", "--show-error", "--retry", "2", f"https://{hostname}/{path}"]),
                    f"public {path}",
                )
                if path == "health":
                    require(payload.get("status") == "ok", "public health is not ok")
                elif path == "ready":
                    require(payload.get("status") == "ready" and payload.get("database") == "ok", "public database readiness is not ok")
                else:
                    require(payload.get("environment") == "aws-dev" and payload.get("version") == EXPECTED_APPLICATION_VERSION, "public release identity changed")
                requests += 1
            sleep_runner(2)
        sleep_runner(final_wait)
    return {"request_count": requests, "paths": ["/health", "/ready", "/version"], "bounded": True}


def read_qualified_telemetry(
    prometheus_reader: PrometheusReader | None = None,
) -> dict[str, Any]:
    if prometheus_reader is None:
        with prometheus_port_forward() as session_reader:
            return read_qualified_telemetry(session_reader)
    identity = f'deployment_environment_name="aws-dev",platform_release_id="{EXPECTED_RELEASE_ID}"'
    request_rate = scalar_query(prometheus_reader, f'demo_api:slo_http_requests:rate30d{{{identity}}}', "request series")
    availability = scalar_query(prometheus_reader, f'demo_api:slo_availability:ratio30d{{{identity}}}', "availability SLO")
    latency = scalar_query(prometheus_reader, f'demo_api:slo_latency:ratio30d{{{identity}}}', "latency SLO")
    critical = query_prometheus(prometheus_reader, 'ALERTS{alertstate="firing",severity="critical",deployment_environment_name="aws-dev"}')
    require(critical.get("status") == "success", "critical alert query failed")
    critical_count = len(critical.get("data", {}).get("result", []))
    require(request_rate > 0, "release-scoped request series is not populated")
    require(0.999 <= availability <= 1.0, "availability SLO is below the reviewed threshold")
    require(0.99 <= latency <= 1.0, "latency SLO is below the reviewed threshold")
    require(critical_count == 0, "critical aws-dev alert is firing")
    return {
        "request_series_ready": True,
        "availability_slo_passed": True,
        "latency_slo_passed": True,
        "critical_alerts_firing": False,
    }


def execute(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_command,
    traffic_runner: TrafficRunner = generate_bounded_traffic,
    now: datetime | None = None,
    prometheus_reader: PrometheusReader | None = None,
) -> dict[str, Any]:
    require(os.environ.get("CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION") == EXECUTION_CONFIRMATION, f"Set CONFIRM_AWS_DEV_RUNTIME_QUALIFICATION={EXECUTION_CONFIRMATION}")
    if prometheus_reader is None:
        with prometheus_port_forward() as session_reader:
            return execute(
                expected_commit,
                git_runner,
                read_runner,
                traffic_runner,
                now,
                session_reader,
            )
    inventory = verify_live_inputs(expected_commit, git_runner, read_runner, now, prometheus_reader)
    traffic = traffic_runner(PUBLIC_HOSTNAME)
    validate_exact_main(expected_commit, git_runner)
    telemetry = read_qualified_telemetry(prometheus_reader)
    final_state = read_live_state(expected_commit, read_runner, prometheus_reader)
    return {
        "status": "aws-dev-runtime-qualification-complete",
        "control_plane_commit": expected_commit,
        "candidate_release_id": EXPECTED_RELEASE_ID,
        "runtime_qualified": True,
        "traffic_generated": True,
        "bounded_request_count": traffic["request_count"],
        **telemetry,
        "final_runtime_healthy": all((final_state["demo_deployment_ready"], final_state["database_ready"], final_state["grafana_deployment_ready"])),
        "progressive_delivery_promoted": False,
        "automatic_teardown_executed": False,
        "qualification_end_utc": inventory["qualification_end_utc"],
        "next_action": "review-separate-aws-dev-runtime-qualification-execution-evidence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    args = parser.parse_args()
    try:
        result = verification_result(verify_live_inputs(args.expected_control_plane_commit)) if args.phase == "verify" else execute(args.expected_control_plane_commit)
    except KeyboardInterrupt:
        parser.exit(130, "aws-dev runtime qualification interrupted; Prometheus port-forward cleaned up\n")
    except (CommandFailure, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"aws-dev runtime qualification stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
