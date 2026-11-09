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


contract_path = "delivery/contracts/v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.2.0.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.2.0.1", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.2.0", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json").is_file(), "Missing predecessor contract")

incident = contract.get("incident", {})
require(incident.get("runtimeConfigurationDefect") is False, "Runtime defect incorrectly claimed")
require(incident.get("acceptanceParserDefect") is True, "Parser defect not recorded")
require(incident.get("redeployRequired") is False, "Redeployment incorrectly required")
require(incident.get("observedRuntimeUrlRepresentation") == "url: <secret>", "Observed redaction changed")
require(incident.get("observedRedactedUrlCount") == 2, "Observed redacted URL count changed")
for key in ("drillReceiversObserved", "webhookConfigsObserved", "sendResolvedObserved"):
    require(incident.get(key) == 2, f"Observed runtime cardinality changed: {key}")
require(incident.get("remainingLiveChecksPassed") is True, "Remaining live evidence omitted")

repair = contract.get("repair", {})
require(repair.get("desiredStateUrlMode") == "exact-internal-literal", "Desired-state URL mode changed")
require(repair.get("fixtureDefaultUrlMode") == "literal", "Fixture default mode changed")
require(repair.get("runtimeUrlMode") == "redacted", "Runtime URL mode changed")
require(repair.get("runtimeUrlLineCount") == 2, "Runtime URL line count changed")
require(repair.get("runtimeRedactedUrlCount") == 2, "Runtime redaction count changed")
for key in (
    "publicUrlFixtureRejected",
    "missingRedactedUrlFixtureRejected",
    "mixedLiteralAndRedactedRuntimeFixtureRejected",
    "normalRouteAndMatcherCardinalityPreserved",
):
    require(repair.get(key) is True, f"Repair requirement disabled: {key}")

unchanged = contract.get("unchanged", {})
require(unchanged.get("localPlatformChartVersion") == "0.4.1", "Local platform Chart changed")
require(unchanged.get("localPlatformApplicationVersion") == "v0.11.5.2.0", "Local platform appVersion changed")
require(unchanged.get("observabilityChartVersion") == "0.4.1", "Observability Chart changed")
require(unchanged.get("observabilityApplicationVersion") == "v0.11.5.1.1", "Observability appVersion changed")
require((unchanged.get("formalAlertCount"), unchanged.get("warningCount"), unchanged.get("criticalCount")) == (9, 2, 7), "Formal alert inventory changed")
for name, flag in unchanged.items():
    if name not in {
        "localPlatformChartVersion",
        "localPlatformApplicationVersion",
        "observabilityChartVersion",
        "observabilityApplicationVersion",
        "formalAlertCount",
        "warningCount",
        "criticalCount",
    }:
        require(flag is False, f"Runtime boundary expanded: {name}")
require(all(value is False for value in contract.get("boundaries", {}).values()), "Repair boundary expanded")

acceptance = contract.get("acceptance", {})
for key in ("offlineValidator", "liveValidator", "liveDrill"):
    require((root / acceptance.get(key, "")).is_file(), f"Missing acceptance script: {key}")
require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
require(acceptance.get("localLiveRerunRequired") is True, "Live rerun optional")
require(acceptance.get("monitoringRedeployBeforeRerun") is False, "Redeploy incorrectly required")
require(acceptance.get("liveDrillRequiredAfterCheckerPasses") is True, "Live drill optional")
require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")

local_chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
tracing_runtime_successor = (root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json").is_file()
require(
    ("version: 0.8.0" if tracing_runtime_successor else ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1"))) in local_chart
    and ('appVersion: "v0.11.6.2.2"' if tracing_runtime_successor else ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"'))) in local_chart,
    "Local platform Chart changed",
)
views_chart = read("platform/observability/helm/Chart.yaml")
slo_foundation_successor = (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()
burn_rate_successor = (root / "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json").is_file()
expected_views = ("version: 0.6.0", 'appVersion: "v0.11.7.1"') if burn_rate_successor else (("version: 0.5.0", 'appVersion: "v0.11.7.0"') if slo_foundation_successor else ("version: 0.4.1", 'appVersion: "v0.11.5.1.1"'))
require(all(marker in views_chart for marker in expected_views), "Observability Chart changed")

internal_base = "http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080"
for relative in ("clusters/local/platform/templates/monitoring.yaml", "clusters/aws/base/platform/monitoring.yaml"):
    text = read(relative)
    require(text.count("webhook_configs:") == 2, f"{relative}: webhook count changed")
    require(text.count("send_resolved: true") == 2, f"{relative}: resolved count changed")
    require(text.count(f"url: {internal_base}/critical") == 1, f"{relative}: critical internal URL changed")
    require(text.count(f"url: {internal_base}/warning") == 1, f"{relative}: warning internal URL changed")
    require("url: <secret>" not in text, f"{relative}: runtime redaction leaked into desired state")

alerts = re.findall(r"(?m)^\s*- alert:\s*(\S+)\s*$", read("platform/observability/helm/templates/actionable-alerts.yaml"))
require(len(alerts) == 9 and len(set(alerts)) == 9, "Nine-alert inventory changed")
require(sum(name.endswith("Warning") for name in alerts) == 2, "Warning inventory changed")

checker = read("scripts/check-alertmanager.sh")
for marker in (
    "ALERTMANAGER_CONFIG_FIXTURE_URL_MODE",
    'fixture_url_mode=literal',
    'assert_active_alertmanager_config "${config_text}" "${expect_drill}" redacted',
    "exactly two redacted drill webhook URL lines",
    "redacted_url_count",
    "url: <secret>",
    "v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.json",
):
    require(marker in checker, f"Checker lacks repair marker: {marker}")
require("active Alertmanager drill configuration is missing: url:" not in checker, "Legacy live plaintext URL assertion remains")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.sh"),
    ("README.md", "v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair"),
    ("docs/ROADMAP.md", "v0.11.5.2.0.1"),
    ("docs/OBSERVABILITY.md", "url: <secret>"),
    ("docs/V0.11.5.2.0_ALERT_LIFECYCLE_DRILL.md", "v0.11.5.2.0.1"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.5.2.0.1"),
    ("CHANGELOG.md", "## v0.11.5.2.0.1"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Required integration marker missing: {relative}: {marker}")

print("v0.11.5.2.0.1 runtime URL redaction semantics, unchanged desired state, and repair boundaries passed.")
PY

fixture_dir="$(mktemp -d)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

cat >"${fixture_dir}/redacted.yaml" <<'YAML'
global:
  slack_app_url: https://slack.com/api/chat.postMessage
  pagerduty_url: https://events.pagerduty.com/v2/enqueue
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
      - send_resolved: true
        url: <secret>
  - name: warning-drill-webhook
    webhook_configs:
      - send_resolved: true
        url: <secret>
YAML

ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/redacted.yaml" \
ALERTMANAGER_CONFIG_FIXTURE_URL_MODE=redacted \
  "${ROOT_DIR}/scripts/check-alertmanager.sh" >/dev/null

python3 - "${fixture_dir}/redacted.yaml" "${fixture_dir}/missing.yaml" "${fixture_dir}/mixed.yaml" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
Path(sys.argv[2]).write_text(source.replace("        url: <secret>\n", "", 1))
Path(sys.argv[3]).write_text(source.replace("url: <secret>", "url: https://public.example.invalid/critical", 1))
PY

for invalid in missing mixed; do
  if ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/${invalid}.yaml" \
    ALERTMANAGER_CONFIG_FIXTURE_URL_MODE=redacted \
      "${ROOT_DIR}/scripts/check-alertmanager.sh" >"${fixture_dir}/${invalid}.log" 2>&1; then
    echo "ERROR: redacted runtime fixture unexpectedly passed: ${invalid}." >&2
    exit 1
  fi
  grep -F -- 'must contain exactly two redacted drill webhook URL lines' \
    "${fixture_dir}/${invalid}.log" >/dev/null || {
      echo "ERROR: redacted runtime diagnostic changed: ${invalid}." >&2
      cat "${fixture_dir}/${invalid}.log" >&2
      exit 1
    }
done

echo "v0.11.5.2.0.1 exact redacted, missing-redaction, and mixed-runtime fixtures passed."
