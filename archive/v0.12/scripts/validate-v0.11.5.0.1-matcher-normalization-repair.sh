#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


root = Path(sys.argv[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


contract = json.loads(read("delivery/contracts/v0.11.5.0.1-matcher-normalization-repair.json"))
require(contract.get("schemaVersion") == "v0.11.5.0.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.0.1", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.0", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.0-alertmanager-foundation.json").is_file(), "Missing predecessor contract")

incident = contract.get("incident", {})
require(incident.get("runtimeConfigurationDefect") is False, "Runtime defect incorrectly claimed")
require(incident.get("redeployRequired") is False, "Redeployment incorrectly required")
require(incident.get("observedCanonicalCriticalMatcher") == 'severity="critical"', "Critical evidence changed")
require(incident.get("observedCanonicalWarningMatcher") == 'severity="warning"', "Warning evidence changed")

repair = contract.get("repair", {})
require(repair.get("formatInsensitiveMatcherValidation") is True, "Format-insensitive validation disabled")
require(repair.get("optionalWhitespaceAroundEquals") is True, "Optional whitespace not accepted")
require(repair.get("expectedCriticalMatcherCount") == 2, "Critical matcher count changed")
require(repair.get("expectedWarningMatcherCount") == 2, "Warning matcher count changed")
require(repair.get("routeAndInhibitionMatchersRequired") is True, "Matcher semantics weakened")
require(repair.get("spacedFixtureAccepted") is True, "Spaced fixture not required")
require(repair.get("canonicalCompactFixtureAccepted") is True, "Compact fixture not required")
require(repair.get("incompleteMatcherFixtureRejected") is True, "Negative fixture not required")
require(all(value is False for value in contract.get("boundaries", {}).values()), "Repair boundary expanded")

acceptance = contract.get("acceptance", {})
require((root / acceptance.get("offlineValidator", "")).is_file(), "Missing offline validator")
require((root / acceptance.get("liveValidator", "")).is_file(), "Missing live validator")
require(acceptance.get("completeQualityGateRequired") is True, "Complete quality gate is optional")
require(acceptance.get("localLiveRerunRequired") is True, "Live rerun is optional")
require(acceptance.get("redeployBeforeLiveRerun") is False, "Repair wrongly requires redeployment")

checker = read("scripts/check-alertmanager.sh")
alert_lifecycle_drill_successor = (root / "delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json").is_file()
for marker in (
    "ALERTMANAGER_CONFIG_FIXTURE",
    "assert_active_alertmanager_config",
    "severity[[:space:]]*=[[:space:]]*",
    "expected_matcher_count=2",
    'matcher_count}" -ne "${expected_matcher_count}"',
    "Observed severity matcher lines:",
):
    require(marker in checker, f"Matcher checker is missing: {marker}")
if alert_lifecycle_drill_successor:
    require("v0.11.5.2.0-alert-lifecycle-drill.json" in checker, "Matcher checker is not drill-successor aware")
require("'severity = \"critical\"'" not in checker, "Legacy exact critical comparison remains")
require("'severity = \"warning\"'" not in checker, "Legacy exact warning comparison remains")

for relative, marker in (
    ("CHANGELOG.md", "## v0.11.5.0.1"),
    ("README.md", "v0.11.5.0.1-matcher-normalization-repair"),
    ("docs/V0.11.5.0_ALERTMANAGER_FOUNDATION.md", "v0.11.5.0.1"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.5.0.1"),
    ("docs/ROADMAP.md", "v0.11.5.0.1"),
):
    require(marker in read(relative), f"{relative}: missing repair marker")
PY

fixture_dir="$(mktemp -d)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

write_fixture() {
  local path="$1"
  local matcher_style="$2"
  local include_inhibition="$3"
  local critical warning

  if [ "${matcher_style}" = "spaced" ]; then
    critical='severity = "critical"'
    warning='severity = "warning"'
  else
    critical='severity="critical"'
    warning='severity="warning"'
  fi

  {
    printf '%s\n' \
      'route:' \
      '  receiver: platform-observation' \
      '  group_by:' \
      '  - environment' \
      '  - cluster' \
      '  - component' \
      '  - alert_family' \
      '  group_wait: 30s' \
      '  group_interval: 5m' \
      '  repeat_interval: 4h' \
      '  routes:' \
      '  - receiver: critical-observation' \
      "    - ${critical}" \
      '  - receiver: warning-observation' \
      "    - ${warning}" \
      'receivers:' \
      '- name: platform-observation' \
      '- name: critical-observation' \
      '- name: warning-observation'
    if [ "${include_inhibition}" = "true" ]; then
      printf '%s\n' \
        'inhibit_rules:' \
        '  source_matchers:' \
        "  - ${critical}" \
        '  target_matchers:' \
        "  - ${warning}" \
        '  equal:' \
        '  - environment' \
        '  - cluster' \
        '  - component' \
        '  - alert_family'
    fi
  } >"${path}"
}

write_fixture "${fixture_dir}/spaced.yaml" spaced true
write_fixture "${fixture_dir}/compact.yaml" compact true
write_fixture "${fixture_dir}/incomplete.yaml" compact false

for fixture in spaced compact; do
  ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/${fixture}.yaml" \
    "${ROOT_DIR}/scripts/check-alertmanager.sh" >/dev/null
done

if ALERTMANAGER_CONFIG_FIXTURE="${fixture_dir}/incomplete.yaml" \
  "${ROOT_DIR}/scripts/check-alertmanager.sh" >"${fixture_dir}/negative.log" 2>&1; then
  echo "ERROR: incomplete route-only matcher fixture unexpectedly passed." >&2
  exit 1
fi
grep -F -- 'must contain exactly 2 critical severity matchers; found 1' \
  "${fixture_dir}/negative.log" >/dev/null || {
    echo "ERROR: incomplete matcher diagnostic changed." >&2
    cat "${fixture_dir}/negative.log" >&2
    exit 1
  }

echo "v0.11.5.0.1 matcher normalization, cardinality, diagnostics, and boundary contracts passed."
