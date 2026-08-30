#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
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


def validate_contract(value: dict, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.3.5", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.5", "Bad version")
    require(value.get("status") == "offline-implemented-live-recovery-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    require(incident.get("application") == "startup-devops-root", "Wrong incident Application")
    require(incident.get("errorClass") == "ComparisonError", "Wrong error class")
    require(incident.get("missingPath") == "clusters/local/platform/Chart.yaml", "Wrong missing path")
    require(incident.get("rootSourceType") == "helm", "Wrong source type")
    require(incident.get("requestedRevision") == "HEAD", "Wrong requested revision")
    require(incident.get("childPruneIndicatorsWereSecondary") is True, "Unsafe prune interpretation")
    require(incident.get("clusterRebuildRequired") is False, "Unnecessary rebuild required")

    preflight = value.get("sourcePreflight", {})
    require(preflight.get("requiredPath") == "clusters/local/platform/Chart.yaml", "Wrong preflight path")
    for key in (
        "remoteRevisionResolvedBeforeKubernetes",
        "remoteRevisionFetchedBeforeKubernetes",
        "requiredPathCheckedBeforeKubernetes",
        "missingPathFailsWithoutKubernetesMutation",
    ):
        require(preflight.get(key) is True, f"Source preflight disabled: {key}")

    modes = value.get("restorationModes", {})
    pre_merge = modes.get("preMerge", {})
    require(pre_merge.get("script") == "scripts/restore-local-feature-baseline.sh", "Wrong pre-merge script")
    require(pre_merge.get("declaredRevision") == "resolved-full-commit-sha", "Mutable pre-merge baseline")
    require(pre_merge.get("localCommitMustMatchRemote") is True, "Local/remote equality disabled")
    require(pre_merge.get("trackedWorkingTreeMustBeClean") is True, "Dirty feature baseline accepted")
    require(pre_merge.get("localImageEnabled") is False, "Feature baseline retains local image")
    require(pre_merge.get("rootAutomationRestored") is True, "Feature baseline automation missing")

    post_merge = modes.get("postMerge", {})
    require(post_merge.get("script") == "scripts/restore-local-gitops-head.sh", "Wrong post-merge script")
    require(post_merge.get("declaredRevision") == "HEAD", "Post-merge HEAD changed")
    require(post_merge.get("remoteHeadMustContainRequiredPath") is True, "Old HEAD may be applied")
    require(post_merge.get("localImageEnabled") is False, "HEAD retains local image")
    require(modes.get("sharedImplementation") == "scripts/restore-local-gitops-baseline.sh", "Shared restore missing")

    safety = value.get("comparisonSafety", {})
    for key in (
        "comparisonErrorBlocksSync",
        "comparisonErrorBlocksPrune",
        "comparisonReadinessIsBounded",
    ):
        require(safety.get(key) is True, f"Comparison safety disabled: {key}")
    require(safety.get("directChildSetOrUnsetRequired") is False, "Direct child mutation returned")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


contract = json.loads(read("delivery/contracts/v0.11.3.5-pre-merge-baseline-restoration.json"))
validate_contract(contract)

revision = read("scripts/lib/git-revision.sh")
deploy_root = read("scripts/deploy-root-app.sh")
restore_shared = read("scripts/restore-local-gitops-baseline.sh")
restore_feature = read("scripts/restore-local-feature-baseline.sh")
restore_head = read("scripts/restore-local-gitops-head.sh")

for marker in (
    "assert_remote_git_revision_contains_path",
    "git fetch --quiet --no-tags",
    "git cat-file -e",
    "No Kubernetes resource was changed",
):
    require(marker in revision, f"Revision content guard missing: {marker}")

preflight_call = deploy_root.index("assert_remote_git_revision_contains_path")
kubernetes_call = deploy_root.index('kubectl get namespace "$ARGOCD_NAMESPACE"')
require(preflight_call < kubernetes_call, "Root source preflight occurs after Kubernetes access")
for marker in ("REQUIRED_ROOT_SOURCE_PATH", "resolved_root_revision", "Resolved root source commit"):
    require(marker in deploy_root, f"Root preflight marker missing: {marker}")

for marker in (
    "wait_for_comparison_ready",
    "ComparisonError",
    "No sync or prune operation was started",
    'GIT_TARGET_REVISION="${TARGET_REVISION}"',
    "LOCAL_IMAGE_ENABLED=false",
    'set_application_automation "${ROOT_APP_NAME}"',
):
    require(marker in restore_shared, f"Shared restoration guard missing: {marker}")
for forbidden in ("argocd app set", "argocd app unset", "--prune"):
    require(forbidden not in restore_shared, f"Unsafe restoration mutation returned: {forbidden}")

for marker in (
    "resolve_remote_git_revision",
    "git rev-parse HEAD",
    "git diff --quiet",
    'TARGET_REVISION="${resolved_target_revision}"',
    "Pre-merge feature baseline",
):
    require(marker in restore_feature, f"Pre-merge restoration guard missing: {marker}")
require("TARGET_REVISION=HEAD" in restore_head, "HEAD wrapper is not fixed to HEAD")
require("Post-merge HEAD baseline" in restore_head, "HEAD boundary is undocumented")

for name, mutate in (
    ("Kubernetes preflight disabled", lambda v: v["sourcePreflight"].update(missingPathFailsWithoutKubernetesMutation=False)),
    ("mutable feature baseline", lambda v: v["restorationModes"]["preMerge"].update(declaredRevision="branch")),
    ("old HEAD accepted", lambda v: v["restorationModes"]["postMerge"].update(remoteHeadMustContainRequiredPath=False)),
    ("comparison sync allowed", lambda v: v["comparisonSafety"].update(comparisonErrorBlocksSync=False)),
    ("production expansion", lambda v: v["boundaries"].update(productionAutomationChanged=True)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValueError:
        continue
    raise ValueError(f"Negative case accepted: {name}")

print("v0.11.3.5 pre-merge baseline restoration contract and static validation passed.")
PY

WORK_DIR="$(mktemp -d)"
TRACE_CORRELATION_SUCCESSOR=false
if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.6.2.2-real-demo-api-trace-log-correlation.json" ]; then
  TRACE_CORRELATION_SUCCESSOR=true
fi
export TRACE_CORRELATION_SUCCESSOR
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/git" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
sha="${FAKE_GIT_SHA:-0123456789abcdef0123456789abcdef01234567}"
case "${1:-}" in
  ls-remote)
    printf '%s\t%s\n' "${sha}" "${4:-HEAD}"
    ;;
  fetch)
    exit 0
    ;;
  cat-file)
    [ "${FAKE_GIT_PATH_PRESENT:-false}" = "true" ]
    ;;
  rev-parse)
    printf '%s\n' "${sha}"
    ;;
  diff)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
SH

cat >"${WORK_DIR}/bin/argocd" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
exit 0
SH

cat >"${WORK_DIR}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail

printf '%s\n' "$*" >>"${KUBECTL_LOG}"

if [ "${1:-}" = "get" ] && [ "${2:-}" = "namespace" ]; then
  exit 0
fi
if [ "${1:-}" = "apply" ] && [ "${2:-}" = "-f" ]; then
  cp "${3}" "${CAPTURED_ROOT_MANIFEST}"
  exit 0
fi

if [ "${1:-}" = "-n" ]; then
  shift 2
fi

if [ "${1:-}" = "patch" ]; then
  exit 0
fi
if [ "${1:-}" != "get" ]; then
  exit 0
fi

resource="${2:-}"
name="${3:-}"
output=''
for ((index = 1; index <= $#; index++)); do
  if [ "${!index}" = "-o" ]; then
    next=$((index + 1))
    output="${!next}"
    break
  fi
done

case "${resource}:${output}" in
  application:*'.operation}'*)
    exit 0
    ;;
  application:*'.status.operationState.phase}'*)
    printf '%s' 'Succeeded'
    ;;
  application:*'ComparisonError'*)
    exit 0
    ;;
  application:*'.status.sync.status}'*)
    printf '%s' 'Synced'
    ;;
  application:*'.spec.source.targetRevision}'*)
    printf '%s' "${FAKE_DECLARED_REVISION}"
    ;;
  application:*'git.targetRevision'*)
    printf '%s' "${FAKE_DECLARED_REVISION}"
    ;;
  application:*'demoApi.localImage.enabled'*)
    printf '%s' 'false'
    ;;
  application:*'.spec.source.helm.parameters'* )
    if [ "${name}" != "demo-api" ]; then
      exit 0
    fi
    if [ "${TRACE_CORRELATION_SUCCESSOR}" = "true" ]; then
      printf '%s\n' \
        telemetry.tracing.enabled \
        telemetry.tracing.endpoint \
        telemetry.tracing.protocol \
        telemetry.tracing.timeoutSeconds
    fi
    ;;
  application:*'.spec.syncPolicy.automated.selfHeal}'*)
    printf '%s' 'true'
    ;;
  *)
    exit 0
    ;;
esac
SH

chmod +x "${WORK_DIR}/bin/git" "${WORK_DIR}/bin/argocd" "${WORK_DIR}/bin/kubectl"

echo "==> Rejecting pre-merge HEAD without the platform Chart before Kubernetes access"
: >"${WORK_DIR}/kubectl-missing.log"
if (
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  FAKE_GIT_PATH_PRESENT=false \
  KUBECTL_LOG="${WORK_DIR}/kubectl-missing.log" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/missing-root.yaml" \
    ./scripts/restore-local-gitops-head.sh
) >"${WORK_DIR}/missing.out" 2>"${WORK_DIR}/missing.err"; then
  echo "HEAD without Chart.yaml was accepted." >&2
  exit 1
fi
if ! grep -q 'target revision does not contain required source path' "${WORK_DIR}/missing.err"; then
  cat "${WORK_DIR}/missing.err" >&2
  exit 1
fi
if [ -s "${WORK_DIR}/kubectl-missing.log" ]; then
  echo "Kubernetes was contacted after a failed source preflight." >&2
  exit 1
fi

FEATURE_SHA="0123456789abcdef0123456789abcdef01234567"
echo "==> Restoring an immutable pre-merge feature baseline"
: >"${WORK_DIR}/kubectl-feature.log"
if ! (
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  FAKE_GIT_PATH_PRESENT=true \
  FAKE_GIT_SHA="${FEATURE_SHA}" \
  FAKE_DECLARED_REVISION="${FEATURE_SHA}" \
  KUBECTL_LOG="${WORK_DIR}/kubectl-feature.log" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/feature-root.yaml" \
  TARGET_REVISION=feature/test \
  WAIT_TIMEOUT_SECONDS=3 \
  APPLICATION_IDLE_OBSERVATIONS=1 \
  OPERATION_RETRY_DELAY_SECONDS=0 \
    ./scripts/restore-local-feature-baseline.sh
) >"${WORK_DIR}/feature.out" 2>"${WORK_DIR}/feature.err"; then
  cat "${WORK_DIR}/feature.out" >&2
  cat "${WORK_DIR}/feature.err" >&2
  exit 1
fi
grep -q 'Pre-merge feature baseline restored.' "${WORK_DIR}/feature.out"
grep -q "Resolved feature commit:   ${FEATURE_SHA}" "${WORK_DIR}/feature.out"
grep -q "^    targetRevision: ${FEATURE_SHA}$" "${WORK_DIR}/feature-root.yaml"
grep -A1 'name: demoApi.localImage.enabled' "${WORK_DIR}/feature-root.yaml" | grep -q 'value: "false"'

echo "==> Preserving post-merge HEAD restoration when the Chart exists"
: >"${WORK_DIR}/kubectl-head.log"
if ! (
  cd "${ROOT_DIR}"
  PATH="${WORK_DIR}/bin:${PATH}" \
  FAKE_GIT_PATH_PRESENT=true \
  FAKE_DECLARED_REVISION=HEAD \
  KUBECTL_LOG="${WORK_DIR}/kubectl-head.log" \
  CAPTURED_ROOT_MANIFEST="${WORK_DIR}/head-root.yaml" \
  WAIT_TIMEOUT_SECONDS=3 \
  APPLICATION_IDLE_OBSERVATIONS=1 \
  OPERATION_RETRY_DELAY_SECONDS=0 \
    ./scripts/restore-local-gitops-head.sh
) >"${WORK_DIR}/head.out" 2>"${WORK_DIR}/head.err"; then
  cat "${WORK_DIR}/head.out" >&2
  cat "${WORK_DIR}/head.err" >&2
  exit 1
fi
grep -q 'Post-merge HEAD baseline restored.' "${WORK_DIR}/head.out"
grep -q '^    targetRevision: HEAD$' "${WORK_DIR}/head-root.yaml"

echo "v0.11.3.5 pre-merge baseline restoration validation passed."
