#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

INCLUDE_LOGGING_APPS=false
if [[ -f "${ROOT_DIR}/delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json" ]]; then
  INCLUDE_LOGGING_APPS=true
fi
INCLUDE_EVENTS_APP=false
if [[ -f "${ROOT_DIR}/delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json" ]]; then
  INCLUDE_EVENTS_APP=true
fi
INCLUDE_TRACING_APPS=false
if [[ -f "${ROOT_DIR}/delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json" ]]; then
  INCLUDE_TRACING_APPS=true
fi

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


contract_path = root / "delivery/contracts/v0.11.4.0.1-helm-successor-coverage.json"
contract = json.loads(contract_path.read_text())
require(contract.get("schemaVersion") == "v0.11.4.0.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.4.0.1", "Bad version")
require(contract.get("status") == "offline-implemented-complete-quality-gate-required", "Bad status")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")

incident = contract.get("incident", {})
require(incident.get("failedPhase") == "stable-and-feature-platform-helm-render", "Wrong failed phase")
require(incident.get("runtimeResourceDefect") is False, "Runtime defect incorrectly claimed")
require(incident.get("observabilityViewsMustBeRemoved") is False, "Unsafe resource removal accepted")

repair = contract.get("repair", {})
require(repair.get("successorApplication") == "observability-views", "Wrong successor Application")
require(repair.get("stableChildCount") == 6, "Wrong stable child count")
require(repair.get("featureChildCount") == 6, "Wrong feature child count")
require(repair.get("stableObservabilityRevision") == "HEAD", "Stable revision changed")
require(repair.get("featureObservabilityRevision") == "resolved-feature-sha", "Feature revision is mutable")
require(repair.get("externalChartVersionsRemainIndependent") is True, "External versions coupled")
require(all(contract.get("dynamicRegression", {}).values()), "Dynamic regression disabled")
require(all(flag is False for flag in contract.get("boundaries", {}).values()), "Boundary expanded")
require(contract.get("acceptance", {}).get("completeQualityGateRequired") is True, "Quality gate optional")
require(contract.get("acceptance", {}).get("resumeOriginalV0.11.4.0ApplyRunbook") is True, "Original acceptance abandoned")

validator = (root / "scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh").read_text()
for marker in (
    "v0.11.4.0-grafana-recording-rules.json",
    "v0.11.4.1.0-controller-metrics-discovery.json",
    'expected_names.add("observability-views")',
    'same_repository_names.append("observability-views")',
    "for name in same_repository_names:",
):
    require(marker in validator, f"Successor Helm coverage marker missing: {marker}")

for name, mutate in (
    ("five-child successor", lambda value: value["repair"].update(stableChildCount=5)),
    ("removed views", lambda value: value["incident"].update(observabilityViewsMustBeRemoved=True)),
    ("mutable feature", lambda value: value["repair"].update(featureObservabilityRevision="feature-branch")),
    ("runtime expansion", lambda value: value["boundaries"].update(runtimeResourceChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        require(candidate["repair"]["stableChildCount"] == 6, "Bad child count")
        require(candidate["incident"]["observabilityViewsMustBeRemoved"] is False, "Removal accepted")
        require(candidate["repair"]["featureObservabilityRevision"] == "resolved-feature-sha", "Mutable feature accepted")
        require(all(flag is False for flag in candidate["boundaries"].values()), "Boundary expanded")
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.4.0.1 successor contract and static validation passed.")
PY

mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/helm" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail

case "${1:-}" in
  lint)
    exit 0
    ;;
  template)
    revision=HEAD
    shift 2
    while [ "$#" -gt 0 ]; do
      if [ "${1:-}" = "--set-string" ] && [[ "${2:-}" == git.targetRevision=* ]]; then
        revision="${2#git.targetRevision=}"
        shift 2
        continue
      fi
      shift
    done
    cat <<YAML
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: argo-rollouts
spec:
  source:
    targetRevision: 2.41.1
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
spec:
  source:
    targetRevision: 4.11.3
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring
spec:
  source:
    targetRevision: 88.5.0
YAML
    if [ "${INCLUDE_LOGGING_APPS:-false}" = true ]; then
      cat <<'YAML'
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: logging-loki
spec:
  source:
    targetRevision: 18.11.3
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: logging-alloy
spec:
  source:
    targetRevision: 1.11.0
YAML
    fi
    if [ "${INCLUDE_EVENTS_APP:-false}" = true ]; then
      cat <<'YAML'
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: logging-alloy-events
spec:
  source:
    targetRevision: 1.11.0
YAML
    fi
    if [ "${INCLUDE_TRACING_APPS:-false}" = true ]; then
      cat <<YAML
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tracing-tempo
spec:
  source:
    targetRevision: ${revision}
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tracing-otel-collector
spec:
  source:
    targetRevision: 0.172.0
YAML
    fi
    cat <<YAML
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: namespace-guardrails
spec:
  source:
    targetRevision: ${revision}
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: observability-views
spec:
  source:
    targetRevision: ${revision}
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-api
spec:
  source:
    targetRevision: ${revision}
    helm:
YAML
    if [ "${revision}" = HEAD ]; then
      printf '%s\n' '      parameters: []'
    else
      cat <<'YAML'
      parameters:
        - name: image.repository
          value: startup-devops-baseline/demo-api
        - name: image.tag
          value: v0.11.3-local
        - name: image.pullPolicy
          value: Never
        - name: release.applicationVersion
          value: v0.11.3-local
YAML
    fi
    ;;
  *)
    exit 1
    ;;
esac
SH
chmod +x "${WORK_DIR}/bin/helm"

echo "==> Exercising the historical validator's Helm successor branch"
INCLUDE_LOGGING_APPS="${INCLUDE_LOGGING_APPS}" \
INCLUDE_EVENTS_APP="${INCLUDE_EVENTS_APP}" \
  INCLUDE_TRACING_APPS="${INCLUDE_TRACING_APPS}" \
  PATH="${WORK_DIR}/bin:${PATH}" \
  "${ROOT_DIR}/scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh" >/dev/null

echo "v0.11.4.0.1 Helm successor render regression passed."
