#!/usr/bin/env python3
"""Read-only acceptance of one GitOps deployment; no apply or Rollout promote."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
from string import Template
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from common import ROOT, Rejected, config, fingerprint, identity, release, repo_path, run
from flow import input_fingerprint


def kubectl(*args):
    return json.loads(run(["kubectl", "--request-timeout=20s", *args, "-o", "json"],
                          cwd=ROOT, capture_output=True).stdout)


def fetch_json(url):
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
        return json.load(response)


def verify_cluster(application, workload, pods, expected, environment, revision, container_name):
    if application["status"].get("sync", {}).get("status") != "Synced":
        raise Rejected("Argo CD application is not Synced")
    if application["status"].get("sync", {}).get("revision") != revision:
        raise Rejected("Argo CD has not reconciled the requested configuration revision")
    if application["status"].get("health", {}).get("status") != "Healthy":
        raise Rejected("Argo CD application is not Healthy; complete any manual Canary pause first")
    spec, status = workload["spec"], workload.get("status", {})
    desired = spec.get("replicas", 1)
    if desired < 1 or int(status.get("observedGeneration", 0)) < int(workload["metadata"]["generation"]):
        raise Rejected("Workload has not observed its current desired generation")
    if status.get("updatedReplicas", 0) != desired or status.get("readyReplicas", 0) < desired:
        raise Rejected("Desired replicas are not updated and ready")
    if workload["kind"] == "Rollout":
        if (status.get("phase") != "Healthy" or status.get("pauseConditions") or
                status.get("currentPodHash") != status.get("stableRS")):
            raise Rejected("Rollout is paused, incomplete or not stable")
    expected_image = f"{expected['image']['repository']}@{expected['image']['digest']}"
    template = spec["template"]
    annotations = template["metadata"].get("annotations", {})
    if annotations.get("platform.startup.dev/environment") != environment:
        raise Rejected("Live workload environment mismatch")
    if annotations.get("platform.startup.dev/source-commit") != expected["delivery"]["sourceCommit"]:
        raise Rejected("Live workload source commit mismatch")
    candidates = [item for item in template["spec"]["containers"] if item["name"] == container_name]
    if len(candidates) != 1 or candidates[0]["image"] != expected_image:
        raise Rejected("Live workload image differs from the release")
    active = [pod for pod in pods["items"] if not pod["metadata"].get("deletionTimestamp")]
    if len(active) < desired:
        raise Rejected("Not enough active application Pods")
    for pod in active:
        declared = next((item for item in pod["spec"]["containers"] if item["name"] == container_name), {})
        actual = next((item for item in pod.get("status", {}).get("containerStatuses", [])
                       if item["name"] == container_name), {})
        if (declared.get("image") != expected_image or actual.get("ready") is not True or
                expected["image"]["digest"] not in actual.get("imageID", "")):
            raise Rejected("An active Pod is unready or still runs another image")


def verify_http(payload, environment, version):
    if payload.get("environment") != environment or payload.get("version") != version:
        raise Rejected("HTTP smoke response identifies another environment or release")


def verify_metrics(payload):
    if payload.get("status") != "success" or payload.get("data", {}).get("resultType") != "vector":
        raise Rejected("Metrics query did not return a successful instant vector")
    values = [float(item["value"][1]) for item in payload["data"].get("result", [])]
    if not values or not all(math.isfinite(value) for value in values) or not any(value > 0 for value in values):
        raise Rejected("No positive application metrics acceptance result")


@contextmanager
def prometheus_endpoint(cfg):
    runtime = cfg["runtime"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # Port-forward is limited to loopback and cleaned up on every exit.
    process = subprocess.Popen(["kubectl", "--request-timeout=20s", "-n", runtime["prometheus_namespace"],
                                "port-forward", f"svc/{runtime['prometheus_service']}",
                                f"{port}:{runtime['prometheus_port']}", "--address", "127.0.0.1"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise Rejected("Prometheus port-forward failed; check runtime RBAC and connectivity")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise Rejected("Prometheus port-forward did not become ready")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def verify_once(cfg, environment, revision, expected, prometheus):
    app = cfg["application"]
    env = cfg["environments"][environment]
    application = kubectl("-n", "argocd", "get", "application", env["application"])
    resources = application.get("status", {}).get("resources", [])
    matching = [item for item in resources if item["kind"] in ("Deployment", "Rollout")
                and item.get("namespace") == app["namespace"]]
    if len(matching) != 1:
        raise Rejected("Application must reconcile one supported workload")
    item = matching[0]
    workload = kubectl("-n", app["namespace"], "get", item["kind"], item["name"])
    selector = workload["spec"]["selector"]
    if selector.get("matchExpressions") or not selector.get("matchLabels"):
        raise Rejected("Unsupported workload selector")
    labels = ",".join(f"{key}={value}" for key, value in sorted(selector["matchLabels"].items()))
    pods = kubectl("-n", app["namespace"], "get", "pods", "-l", labels)
    verify_cluster(application, workload, pods, expected, environment, revision, app["container"])
    url = os.getenv("DELIVERY_APP_URL") or env["url"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise Rejected("Cloud runtime smoke requires an HTTPS application URL without embedded credentials")
    verify_http(fetch_json(url.rstrip("/") + "/version"), environment, expected["release"]["applicationVersion"])
    # The adapter owns this query. The runtime engine knows no business metric names.
    query = Template(cfg["runtime"]["metrics_query"]).substitute(
        environment=environment, version=expected["release"]["applicationVersion"],
        digest=expected["image"]["digest"])
    verify_metrics(fetch_json(prometheus + "/api/v1/query?" + urlencode({"query": query})))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=["aws-dev", "aws-test", "aws-prod"], required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    try:
        cfg = config()
        if args.environment == "aws-prod" and os.getenv("DELIVERY_PROD_ENABLED") != "true":
            raise Rejected("Production runtime acceptance is disabled")
        if run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True).stdout.strip() != args.revision:
            raise Rejected("Runtime checkout does not match the requested configuration revision")
        if cfg["runtime"].get("log_and_trace_live_acceptance"):
            raise Rejected("This increment supports live metrics acceptance; log/trace backend adapters are not implemented")
        path = repo_path(cfg["environments"][args.environment]["release"])
        expected = release(path)
        deadline = time.monotonic() + max(1, args.timeout)
        with prometheus_endpoint(cfg) as prometheus:
            while True:
                try:
                    verify_once(cfg, args.environment, args.revision, expected, prometheus)
                    break
                except (Rejected, KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
                    if time.monotonic() >= deadline:
                        raise Rejected(f"Runtime acceptance timed out: {error}") from error
                    print(f"Waiting: {error}", flush=True)
                    time.sleep(10)
        report = {"verified": True, "environment": args.environment, "config_revision": args.revision,
                  "release": identity(expected), "release_sha256": fingerprint(path),
                  "inputs_sha256": input_fingerprint(cfg, args.environment),
                  "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                  "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
                  "completed_at": datetime.now(timezone.utc).isoformat(),
                  "checks": ["argocd-revision", "workload-and-pod-image", "http-version", "application-metrics"],
                  "log_trace_live_checked": False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"PASS: {args.environment}; wrote {args.output.name}")
    except (Rejected, KeyError, ValueError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
