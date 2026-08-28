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
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON in {relative}: {error}") from error
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


contract_path = "delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.2.0", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.2.0", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.1.1.1", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.1.1.1-local-acceptance-path-repair.json").is_file(), "Missing predecessor contract")

chart_contract = contract.get("platformChart", {})
require(chart_contract.get("previousVersion") == "0.4.0", "Wrong predecessor platform Chart version")
require(chart_contract.get("version") == "0.4.1", "Wrong platform Chart version")
require(chart_contract.get("applicationVersion") == "v0.11.5.2.0", "Wrong application version")
chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
require(
    ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1")) in chart,
    "Unexpected local platform Chart version",
)
require(
    ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"')) in chart,
    "Unexpected local platform appVersion",
)

routing = contract.get("routing", {})
require(routing.get("normalReceiversUnchanged") == ["platform-observation", "critical-observation", "warning-observation"], "Normal receiver inventory changed")
require(routing.get("drillReceivers") == ["critical-drill-webhook", "warning-drill-webhook"], "Drill receiver inventory changed")
require(routing.get("requiredMatchers") == ["drill=true", "alert_family=alert-lifecycle-drill", "severity"], "Drill matchers changed")
require(routing.get("continue") is True, "Drill route does not continue into the normal severity route")
require((routing.get("groupWait"), routing.get("groupInterval"), routing.get("repeatInterval")) == ("1s", "2s", "1h"), "Drill timers changed")
require(routing.get("sendResolved") is True, "Resolved delivery disabled")
require(routing.get("externalNotificationConfigured") is False, "External notification boundary expanded")

inhibition = contract.get("inhibition", {})
require(inhibition.get("sourceSeverity") == "critical", "Inhibition source changed")
require(inhibition.get("targetSeverity") == "warning", "Inhibition target changed")
require(inhibition.get("equalLabels") == ["environment", "cluster", "component", "alert_family"], "Inhibition equality changed")
require(inhibition.get("warningDeliverySuppressedInPositiveCase") is True, "Positive inhibition is optional")

runtime = contract.get("temporaryRuntime", {})
require(runtime.get("prometheusRule") == "alert-lifecycle-drill", "Temporary PrometheusRule changed")
require(runtime.get("webhookSink") == "alert-lifecycle-drill-sink", "Temporary sink changed")
require(runtime.get("sourceFixture") == "scripts/fixtures/alert-webhook-sink.py", "Sink fixture changed")
require(runtime.get("imageSource") == "currently deployed demo-api image", "Unexpected sink image source")
require(runtime.get("serviceType") == "ClusterIP", "Sink service exposure changed")
for key in ("serviceAccountTokenAutomount",):
    require(runtime.get(key) is False, f"Temporary runtime security changed: {key}")
for key in ("runAsNonRoot", "readOnlyRootFilesystem", "mustBeRemoved"):
    require(runtime.get(key) is True, f"Temporary runtime property changed: {key}")

expected_phases = [
    "preflight",
    "warning-firing-routing-resolved",
    "critical-firing-routing-resolved",
    "positive-inhibition",
    "negative-inhibition-isolation",
    "zero-residual-cleanup",
]
require(contract.get("phases") == expected_phases, "Drill phase sequence changed")
formal = contract.get("formalAlertInventory", {})
require(formal.get("count") == 9, "Formal alert count changed")
require(formal.get("changed") is False, "Formal alert inventory changed")
require(formal.get("mustBeHealthyAndInactiveBeforeAndAfter") is True, "Clean baseline became optional")
require(all(value is False for value in contract.get("boundaries", {}).values()), "v0.11.5.2.0 boundary expanded")

acceptance = contract.get("acceptance", {})
require((root / acceptance.get("offlineValidator", "")).is_file(), "Missing offline validator")
require((root / acceptance.get("liveValidator", "")).is_file(), "Missing live validator")
require(acceptance.get("confirmationFlag") == "CONFIRM_ALERT_DRILL=true", "Confirmation guard changed")
require(acceptance.get("profile") == "local", "Live profile changed")
require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
require(acceptance.get("localLiveAcceptanceRequired") is True, "Local drill optional")
require(acceptance.get("zeroResidualRequired") is True, "Zero residual optional")
require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS execution boundary changed")

formal_alert_template = read("platform/observability/helm/templates/actionable-alerts.yaml")
expected_alert_names = {
    "DemoApiHttpSuccessRatioLowWarning",
    "DemoApiHttpSuccessRatioLowCritical",
    "DemoApiDependencySuccessRatioLowWarning",
    "DemoApiDependencySuccessRatioLowCritical",
    "ArgoRolloutProblem",
    "ArgoCDApplicationUnhealthy",
    "KubernetesDeploymentUnavailable",
    "PostgreSQLCollectionFailed",
    "PrometheusTargetDown",
}
actual_alert_names = set(re.findall(r"(?m)^\s*- alert:\s+(\S+)\s*$", formal_alert_template))
require(actual_alert_names == expected_alert_names, "The exact nine formal alerts changed")
require("drill:" not in formal_alert_template, "Permanent drill label leaked into formal alerts")

profile_paths = (
    "clusters/local/platform/templates/monitoring.yaml",
    "clusters/aws/base/platform/monitoring.yaml",
)
internal_base = "http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080"
for relative in profile_paths:
    text = read(relative)
    require(text.count("receiver: critical-drill-webhook") == 1, f"{relative}: critical drill route count changed")
    require(text.count("receiver: warning-drill-webhook") == 1, f"{relative}: warning drill route count changed")
    require(text.count("name: critical-drill-webhook") == 1, f"{relative}: critical drill receiver count changed")
    require(text.count("name: warning-drill-webhook") == 1, f"{relative}: warning drill receiver count changed")
    require(text.count("webhook_configs:") == 2, f"{relative}: webhook integration count changed")
    require(text.count("send_resolved: true") == 2, f"{relative}: resolved delivery count changed")
    require(text.count("continue: true") == 2, f"{relative}: continue count changed")
    require(text.count("group_wait: 1s") == 2, f"{relative}: drill group_wait count changed")
    require(text.count("group_interval: 2s") == 2, f"{relative}: drill group_interval count changed")
    require(text.count("repeat_interval: 1h") == 2, f"{relative}: drill repeat_interval count changed")
    require(text.count("'drill = \"true\"'") == 2, f"{relative}: drill matcher count changed")
    require(text.count("'alert_family = \"alert-lifecycle-drill\"'") == 2, f"{relative}: alert-family matcher count changed")
    require(text.count("'severity = \"critical\"'") == 3, f"{relative}: critical matcher cardinality changed")
    require(text.count("'severity = \"warning\"'") == 3, f"{relative}: warning matcher cardinality changed")
    require(f"url: {internal_base}/critical" in text, f"{relative}: critical internal URL missing")
    require(f"url: {internal_base}/warning" in text, f"{relative}: warning internal URL missing")
    urls = re.findall(r"(?m)^\s+- url:\s+(\S+)\s*$", text)
    require(urls == [f"{internal_base}/critical", f"{internal_base}/warning"], f"{relative}: non-contract webhook URL found")
    require(text.count("app.kubernetes.io/name: alert-lifecycle-drill-sink") == 1, f"{relative}: sink egress selector count changed")
    require(re.search(r"(?ms)app\.kubernetes\.io/name: alert-lifecycle-drill-sink\n\s+ports:\n\s+- protocol: TCP\n\s+port: 8080", text) is not None, f"{relative}: bounded sink egress missing")
    for forbidden in ("https://hooks.", "slack_configs:", "email_configs:", "pagerduty_configs:", "opsgenie_configs:", "sns_configs:"):
        require(forbidden not in text, f"{relative}: external notification integration found: {forbidden}")

live = read("scripts/check-alert-lifecycle-drill.sh")
for marker in (
    "CONFIRM_ALERT_DRILL",
    'PROFILE}" != "local"',
    "trap cleanup EXIT",
    "currently deployed demo-api image",
    "automountServiceAccountToken: false",
    "runAsNonRoot: true",
    "readOnlyRootFilesystem: true",
    'capabilities:',
    'drop: ["ALL"]',
    "platform.startup.dev/alert-lifecycle-drill=true",
    "wait_prometheus_firing",
    "wait_alertmanager_state",
    "wait_webhook_event",
    "assert_no_webhook_event",
    "wait_no_drill_alerts",
    "positive inhibition",
    "zero-residual cleanup acceptance passed",
):
    require(marker in live, f"Live drill is missing: {marker}")
require(live.count("apply_single_rule") >= 3, "Single-severity lifecycle phases missing")
require(live.count("apply_pair_rules") >= 3, "Inhibition phases missing")
require("aws-dev" not in live and "aws-prod" not in live, "AWS mutation path added early")

sink = read("scripts/fixtures/alert-webhook-sink.py")
for marker in ("/health", "/events", "/reset", "/critical", "/warning", "MAX_BODY_BYTES", "MAX_EVENTS", "ThreadingHTTPServer"):
    require(marker in sink, f"Webhook sink is missing: {marker}")

checker = read("scripts/check-alertmanager.sh")
for marker in (
    "critical-drill-webhook",
    "warning-drill-webhook",
    "exactly two drill webhook integrations",
    "send_resolved: true",
    "v0.11.5.2.0-alert-lifecycle-drill.json",
):
    require(marker in checker, f"Alertmanager checker lacks successor-aware marker: {marker}")

for relative in (
    "scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh",
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    "scripts/validate-v0.11.5.0-alertmanager-foundation.sh",
):
    text = read(relative)
    require("v0.11.5.2.0-alert-lifecycle-drill.json" in text, f"Historical validator is not platform-Chart successor-aware: {relative}")
    require("v0.11.5.2.0" in text and "0.4.1" in text, f"Historical validator lacks the new platform Chart successor: {relative}")
require(
    "v0.11.5.2.0-alert-lifecycle-drill.json" in read("scripts/validate-v0.11.5.0.1-matcher-normalization-repair.sh"),
    "Historical matcher validator is not drill-successor aware",
)
require(
    "v0.11.5.2.0-alert-lifecycle-drill.json" in read("scripts/validate-v0.11.5.1-actionable-alerts-runbooks.sh"),
    "Historical actionable-alert validator is not drill-successor aware",
)

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.2.0-alert-lifecycle-drill.sh"),
    ("docs/V0.11.5.2.0_ALERT_LIFECYCLE_DRILL.md", "## Live acceptance"),
    ("docs/ROADMAP.md", "v0.11.5.2.0"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.5.2.0"),
    ("docs/OBSERVABILITY.md", "check-alert-lifecycle-drill.sh"),
    ("README.md", "v0.11.5.2.0-alert-lifecycle-drill"),
    ("CHANGELOG.md", "## v0.11.5.2.0"),
    (".github/CODEOWNERS", "/scripts/check-alert-lifecycle-drill.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Required integration marker missing: {relative}: {marker}")

print("v0.11.5.2.0 drill routes, internal delivery, inhibition phases, security boundaries, and cleanup contracts passed.")
PY

fixture_dir="$(mktemp -d)"
sink_pid=""
cleanup() {
  if [ -n "${sink_pid}" ]; then
    kill "${sink_pid}" >/dev/null 2>&1 || true
    wait "${sink_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${fixture_dir}"
}
trap cleanup EXIT

sink_port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
SINK_HOST=127.0.0.1 SINK_PORT="${sink_port}" \
  python3 "${ROOT_DIR}/scripts/fixtures/alert-webhook-sink.py" >"${fixture_dir}/sink.log" 2>&1 &
sink_pid="$!"

for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:${sink_port}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl -fsS "http://127.0.0.1:${sink_port}/health" | jq -e '.status == "ok"' >/dev/null
curl -fsS -X POST -H 'Content-Type: application/json' \
  --data '{"status":"firing","receiver":"critical-drill-webhook","alerts":[{"status":"firing","labels":{"alertname":"FixtureCritical","drill_id":"fixture"}}]}' \
  "http://127.0.0.1:${sink_port}/critical" >/dev/null
curl -fsS "http://127.0.0.1:${sink_port}/events" | jq -e '
  (.events | length) == 1 and
  .events[0].path == "/critical" and
  .events[0].payload.status == "firing" and
  .events[0].payload.alerts[0].labels.drill_id == "fixture"
' >/dev/null
curl -fsS -X POST "http://127.0.0.1:${sink_port}/reset" >/dev/null
curl -fsS "http://127.0.0.1:${sink_port}/events" | jq -e '(.events | length) == 0' >/dev/null

cat >"${fixture_dir}/successor.yaml" <<'YAML'
route:
  receiver: platform-observation
  group_by: [environment, cluster, component, alert_family]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - receiver: critical-drill-webhook
      matchers:
        - drill="true"
        - alert_family="alert-lifecycle-drill"
        - severity="critical"
      continue: true
      group_wait: 1s
      group_interval: 2s
      repeat_interval: 1h
    - receiver: warning-drill-webhook
      matchers:
        - drill="true"
        - alert_family="alert-lifecycle-drill"
        - severity="warning"
      continue: true
      group_wait: 1s
      group_interval: 2s
      repeat_interval: 1h
    - receiver: critical-observation
      matchers:
        - severity="critical"
    - receiver: warning-observation
      matchers:
        - severity="warning"
inhibit_rules:
  - source_matchers:
      - severity="critical"
    target_matchers:
      - severity="warning"
    equal: [environment, cluster, component, alert_family]
receivers:
  - name: platform-observation
  - name: critical-observation
  - name: warning-observation
  - name: critical-drill-webhook
    webhook_configs:
      - url: http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080/critical
        send_resolved: true
  - name: warning-drill-webhook
    webhook_configs:
      - url: http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080/warning
        send_resolved: true
YAML

ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/successor.yaml" \
  "${ROOT_DIR}/scripts/check-alertmanager.sh" >/dev/null
sed 's#alert-lifecycle-drill-sink.observability.svc.cluster.local:8080/critical#public.example.invalid/critical#' \
  "${fixture_dir}/successor.yaml" >"${fixture_dir}/public-url.yaml"
if ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/public-url.yaml" \
  "${ROOT_DIR}/scripts/check-alertmanager.sh" >"${fixture_dir}/negative.log" 2>&1; then
  echo "ERROR: Alertmanager checker accepted a non-contract webhook URL." >&2
  exit 1
fi

echo "v0.11.5.2.0 webhook fixture and Alertmanager successor fixtures passed."
