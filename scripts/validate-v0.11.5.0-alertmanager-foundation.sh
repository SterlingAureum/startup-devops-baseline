#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any


root = Path(sys.argv[1])


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


def load_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads(read(relative))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {relative}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def require_markers(relative: str, expected: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in expected:
        require(marker in text, f"{relative}: missing marker {marker!r}")
    return text


contract_path = "delivery/contracts/v0.11.5.0-alertmanager-foundation.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.0", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.0", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-required", "Bad status")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")

ownership = contract.get("ownership", {})
require(ownership.get("runtimeApplication") == "monitoring", "Wrong runtime Application")
require(ownership.get("runtimeChart") == "kube-prometheus-stack", "Wrong runtime Chart")
require(ownership.get("runtimeChartVersion") == "88.5.0", "Monitoring Chart version drift")
require(ownership.get("configurationOwner") == "monitoring Application Helm values", "Wrong configuration owner")
require(ownership.get("alertRuleOwner") == "platform/observability/helm", "Wrong alert-rule owner")
require(ownership.get("alertmanagerConfigCrdAdded") is False, "AlertmanagerConfig CRD unexpectedly added")

expected_profiles = {
    "local": (1, "6h", "emptyDir", "512Mi"),
    "aws-dev": (1, "24h", "gp3-pvc", "2Gi"),
    "aws-test": (1, "48h", "gp3-pvc", "2Gi"),
    "aws-prod": (1, "168h", "gp3-pvc", "5Gi"),
}
profiles = contract.get("profiles", {})
require(set(profiles) == set(expected_profiles), "Environment profile set changed")
for name, expected in expected_profiles.items():
    actual = profiles[name]
    require(
        (actual.get("replicas"), actual.get("retention"), actual.get("storageType"), actual.get("storageSize")) == expected,
        f"Profile changed: {name}",
    )

routing = contract.get("routing", {})
require(routing.get("defaultReceiver") == "platform-observation", "Default receiver changed")
require(routing.get("severityReceivers") == ["critical-observation", "warning-observation"], "Severity receivers changed")
require(routing.get("groupBy") == ["environment", "cluster", "component", "alert_family"], "Grouping labels changed")
require(routing.get("groupWait") == "30s", "group_wait changed")
require(routing.get("groupInterval") == "5m", "group_interval changed")
require(routing.get("repeatInterval") == "4h", "repeat_interval changed")
require(routing.get("externalNotificationConfigured") is False, "External notification configured early")

inhibition = contract.get("inhibition", {})
require(inhibition.get("sourceSeverity") == "critical", "Inhibition source changed")
require(inhibition.get("targetSeverity") == "warning", "Inhibition target changed")
require(inhibition.get("equalLabels") == ["environment", "cluster", "component", "alert_family"], "Inhibition labels changed")

security = contract.get("securityAndCost", {})
require(security.get("serviceType") == "ClusterIP", "Alertmanager service exposed")
require(security.get("publicIngress") is False, "Alertmanager Ingress enabled")
require(security.get("serviceAccountTokenAutomount") is False, "Alertmanager token automount enabled")
require(security.get("resourceRequestsAndLimits") is True, "Alertmanager resources unbounded")
require(security.get("networkPolicy") == "alertmanager-cluster-only", "NetworkPolicy changed")
require(security.get("awsNodeSelector") == "workload=system", "AWS placement changed")
require(security.get("awsStorageClass") == "gp3-observability-alertmanager", "AWS StorageClass changed")
require(security.get("awsStorageEncrypted") is True, "AWS storage encryption disabled")
require(security.get("awsStorageReclaimPolicy") == "Delete", "AWS reclaim policy changed")
for false_key in ("plaintextNotificationCredentialCommitted", "highAvailabilityClaimed"):
    require(security.get(false_key) is False, f"Security boundary expanded: {false_key}")

require(all(value is False for value in contract.get("boundaries", {}).values()), "Version boundary expanded")
acceptance = contract.get("acceptance", {})
require((root / acceptance.get("offlineValidator", "")).is_file(), "Missing offline validator")
require((root / acceptance.get("liveValidator", "")).is_file(), "Missing live validator")
require(acceptance.get("requireNoAlertRulesFlag") == "REQUIRE_NO_ALERT_RULES=true", "No-alert flag changed")
require(acceptance.get("completeQualityGateRequired") is True, "Complete quality gate is optional")
require(acceptance.get("localLiveReplayRequiredBeforeTag") is True, "Local replay is optional")
require(acceptance.get("awsLiveEvidenceDeferredTo") == "v0.11.8", "AWS evidence boundary changed")

common_markers = (
    "alertmanager:",
    "enabled: true",
    "type: ClusterIP",
    "resolve_timeout: 5m",
    "receiver: platform-observation",
    "group_wait: 30s",
    "group_interval: 5m",
    "repeat_interval: 4h",
    "severity = \"critical\"",
    "severity = \"warning\"",
    "- environment",
    "- cluster",
    "- component",
    "- alert_family",
    "name: critical-observation",
    "name: warning-observation",
    "replicas: 1",
    "automountServiceAccountToken: false",
    "cpu: 50m",
    "memory: 64Mi",
    "cpu: 200m",
    "memory: 256Mi",
    "name: alertmanager-cluster-only",
    "app.kubernetes.io/name: alertmanager",
    "port: 9093",
    "port: 9094",
)

local = require_markers("clusters/local/platform/templates/monitoring.yaml", common_markers + (
    "retention: 6h",
    "sizeLimit: 512Mi",
))
aws = require_markers("clusters/aws/base/platform/monitoring.yaml", common_markers + (
    "targetRevision: 88.5.0",
    "retention: 24h",
    "workload: system",
    "storageClassName: gp3-observability-alertmanager",
    "storage: 2Gi",
    "name: gp3-observability-alertmanager",
    "tagSpecification_3: Component=observability-alertmanager",
    "encrypted: \"true\"",
    "reclaimPolicy: Delete",
))

for text, label in ((local, "local"), (aws, "AWS")):
    require(re.search(r"(?ms)defaultRules:\n\s+create: false", text) is not None, f"{label}: default rules enabled")
    require(re.search(r"(?ms)alertmanager:\n\s+enabled: true", text) is not None, f"{label}: Alertmanager disabled")
    require(re.search(r"(?ms)alertmanager:.*?ingress:\n\s+enabled: false", text) is not None, f"{label}: Alertmanager Ingress enabled")
    require(text.count("name: alertmanager-cluster-only") == 1, f"{label}: Alertmanager NetworkPolicy count changed")
    for forbidden in (
        "webhook_configs:", "slack_configs:", "email_configs:", "pagerduty_configs:",
        "sns_configs:", "opsgenie_configs:", "victorops_configs:", "telegram_configs:",
        "type: LoadBalancer", "type: NodePort",
    ):
        require(forbidden not in text, f"{label}: forbidden Alertmanager boundary: {forbidden}")

require_markers("clusters/local/platform/Chart.yaml", ("version: 0.4.0", 'appVersion: "v0.11.5.0"'))
semantic_repair_successor = (root / "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json").is_file()
actionable_alerts_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()
require_markers(
    "platform/observability/helm/Chart.yaml",
    (
        "version: 0.4.1" if semantic_repair_successor else ("version: 0.4.0" if actionable_alerts_successor else "version: 0.3.1"),
        'appVersion: "v0.11.5.1.1"' if semantic_repair_successor else ('appVersion: "v0.11.5.1"' if actionable_alerts_successor else 'appVersion: "v0.11.4.2.1"'),
    ),
)

test_overlay = require_markers("clusters/aws/overlays/test/kustomization.yaml", (
    "/alertmanager/alertmanagerSpec/retention",
    "value: 48h",
    "/extraManifests/1/parameters/tagSpecification_2",
    "value: Environment=test",
))
prod_overlay = require_markers("clusters/aws/overlays/prod/kustomization.yaml", (
    "/alertmanager/alertmanagerSpec/retention",
    "value: 168h",
    "/alertmanager/alertmanagerSpec/storage/volumeClaimTemplate/spec/resources/requests/storage",
    "value: 5Gi",
    "/extraManifests/1/parameters/tagSpecification_2",
    "value: Environment=prod",
))
require(test_overlay.count("/alertmanager/alertmanagerSpec/retention") == 1, "aws-test Alertmanager retention patch changed")
require(prod_overlay.count("/alertmanager/alertmanagerSpec/retention") == 1, "aws-prod Alertmanager retention patch changed")

active_yaml = "\n".join(
    path.read_text()
    for base in (root / "clusters", root / "platform")
    for path in base.rglob("*.yaml")
)
require("kind: AlertmanagerConfig" not in active_yaml, "AlertmanagerConfig CRD added before it is needed")

alert_rules_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()
if not alert_rules_successor:
    views_templates = "\n".join(path.read_text() for path in (root / "platform/observability/helm/templates").glob("*.yaml"))
    require(re.search(r"(?m)^\s*- alert:\s*", views_templates) is None, "v0.11.5.0 added an alert rule")

require_markers("scripts/check-alertmanager.sh", (
    "/-/ready",
    "/api/v2/status",
    "/api/v1/alertmanagers",
    "alertmanager_build_info",
    "REQUIRE_NO_ALERT_RULES",
))
require_markers("docs/V0.11.5.0_ALERTMANAGER_FOUNDATION.md", (
    "# v0.11.5.0 Alertmanager and Alerting Policy Foundation",
    "REQUIRE_NO_ALERT_RULES=true",
    "v0.11.5.1",
    "v0.11.8",
))

print("v0.11.5.0 Alertmanager runtime, routing, storage, security, and acceptance contracts passed.")
PY
