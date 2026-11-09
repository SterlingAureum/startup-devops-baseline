#!/usr/bin/env python3
"""Validate the supported single HTTP-workload wiring, without cluster access."""
import argparse
from pathlib import Path
import sys
from urllib.parse import urlsplit

import yaml

from common import DIGEST, Rejected, UniqueLoader


def require(condition, message):
    if not condition:
        raise Rejected(message)


def matches(selector, labels):
    return bool(selector) and all(labels.get(key) == value for key, value in selector.items())


def validate(documents, environment, namespace, metrics_required=True,
             environment_annotation="platform.startup.dev/environment"):
    documents = [item for item in documents if item is not None]
    require(all(isinstance(item, dict) and item.get("kind") for item in documents), "Expected Kubernetes objects")
    require(not any(item["kind"] == "List" for item in documents), "Flatten Lists before validation")
    seen = set()
    for item in documents:
        meta = item.get("metadata", {})
        require(meta.get("namespace", namespace) == namespace, "Application resource namespace mismatch")
        key = (item.get("apiVersion"), item["kind"], meta.get("name"))
        require(meta.get("name") and key not in seen, "Missing or duplicate resource identity")
        seen.add(key)
    workloads = [item for item in documents if item["kind"] in ("Deployment", "Rollout")]
    require(len(workloads) == 1, "Expected exactly one Deployment or Rollout")
    workload = workloads[0]
    require(workload.get("apiVersion") == {"Deployment": "apps/v1", "Rollout": "argoproj.io/v1alpha1"}[workload["kind"]],
            "Unsupported workload API version")
    spec = workload["spec"]
    pod = spec["template"]
    labels = pod["metadata"].get("labels", {})
    selector = spec.get("selector", {})
    require(not selector.get("matchExpressions"), "Workload matchExpressions are outside this adapter")
    require(matches(selector.get("matchLabels", {}), labels), "Workload selector does not match pod labels")
    require(pod["metadata"].get("annotations", {}).get(environment_annotation) == environment,
            "Pod environment annotation mismatch")
    containers = pod["spec"].get("containers", [])
    require(bool(containers), "No application containers")
    named_ports, numeric_ports = {}, set()
    for container in containers:
        for port in container.get("ports", []):
            number = port.get("containerPort")
            require(type(number) is int and 0 < number < 65536, "Invalid container port")
            numeric_ports.add(number)
            if port.get("name"):
                require(port["name"] not in named_ports, "Ambiguous named container port")
                named_ports[port["name"]] = number
    for container in containers:
        probe = container.get("readinessProbe", {})
        handlers = [key for key in ("httpGet", "tcpSocket", "exec", "grpc") if key in probe]
        require(len(handlers) == 1, "Readiness probe must declare exactly one supported handler")
        handler = probe[handlers[0]]
        require(isinstance(handler, dict), "Invalid readiness handler")
        if handlers[0] == "exec":
            require(isinstance(handler.get("command"), list) and bool(handler["command"]), "Empty exec readiness probe")
        else:
            port = handler.get("port")
            require((type(port) is int and port in numeric_ports) or
                    (isinstance(port, str) and port in named_ports), "Readiness probe port is not declared")
            if handlers[0] == "httpGet":
                require(str(handler.get("path", "")).startswith("/"), "Invalid readiness HTTP path")
        values = {item["name"]: item["value"] for item in container.get("env", []) if "value" in item}
        if "APP_ENV" in values:
            require(values["APP_ENV"] == environment, "APP_ENV disagrees with target environment")
        if str(values.get("TRACING_ENABLED", "false")).lower() == "true":
            protocol = values.get("OTEL_EXPORTER_OTLP_PROTOCOL")
            endpoint = values.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", values.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
            parsed = urlsplit(endpoint)
            require(protocol in ("grpc", "http/protobuf") and parsed.scheme in ("http", "https")
                    and parsed.hostname and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment, "Invalid declared OTLP transport")
    for container in containers + pod["spec"].get("initContainers", []):
        image = container.get("image", "")
        require(bool(image), "Missing image")
        if environment != "local":
            require("@" in image and DIGEST.fullmatch(image.rsplit("@", 1)[1]),
                    "Cloud containers, including init containers, must pin an image digest")
    services = [item for item in documents if item["kind"] == "Service"]
    require(bool(services), "No application Service")
    for service in services:
        require(matches(service["spec"].get("selector", {}), labels), "Service selector does not match application")
        ports = service["spec"].get("ports", [])
        require(bool(ports), "Service has no ports")
        for port in ports:
            target = port.get("targetPort", port.get("port"))
            require((type(target) is int and target in numeric_ports) or
                    (isinstance(target, str) and target in named_ports), "Service targetPort is not declared")
    monitors = [item for item in documents if item["kind"] == "ServiceMonitor"]
    require(not metrics_required or bool(monitors), "Metrics profile requires a ServiceMonitor")
    for monitor in monitors:
        monitor_spec = monitor["spec"]
        ns = monitor_spec.get("namespaceSelector", {})
        require(not ns.get("any") and ns.get("matchNames", [namespace]) in ([], [namespace]),
                "ServiceMonitor targets an unexpected namespace")
        selector = monitor_spec.get("selector", {})
        require(not selector.get("matchExpressions"), "ServiceMonitor matchExpressions are outside this adapter")
        selected = [service for service in services if matches(selector.get("matchLabels", {}), service["metadata"].get("labels", {}))]
        require(bool(selected), "ServiceMonitor selects no application Service")
        require(bool(monitor_spec.get("endpoints")), "ServiceMonitor has no endpoints")
        for endpoint in monitor_spec["endpoints"]:
            require(str(endpoint.get("path", "/metrics")).startswith("/"), "Invalid metrics path")
            require(isinstance(endpoint.get("port"), str) and bool(endpoint["port"]), "Metrics endpoint must name a Service port")
            for service in selected:
                require(endpoint.get("port") in {port.get("name") for port in service["spec"]["ports"]},
                        "ServiceMonitor endpoint does not name a Service port")
    return workload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifests", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--metrics-optional", action="store_true")
    parser.add_argument("--environment-annotation", default="platform.startup.dev/environment")
    args = parser.parse_args()
    try:
        validate(list(yaml.load_all(args.manifests.read_text(), Loader=UniqueLoader)), args.environment,
                 args.namespace, not args.metrics_optional, args.environment_annotation)
    except (Rejected, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    print("PASS: supported HTTP workload deployment and metrics wiring")
    return 0


if __name__ == "__main__":
    sys.exit(main())
