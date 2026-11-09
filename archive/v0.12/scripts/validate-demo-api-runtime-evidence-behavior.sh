#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

WRITER="${ROOT_DIR}/scripts/write-demo-api-runtime-evidence.sh"
VALIDATOR="${ROOT_DIR}/scripts/validate-demo-api-runtime-evidence.sh"
REVISION="$(printf 'a%.0s' {1..40})"
ALB_HASH="$(printf 'b%.0s' {1..64})"
EVIDENCE_ID="20990102030405"
RECORDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

record_fixture() {
  local environment="$1"
  local cluster application kind hostname rollout_phase analysis_name analysis_phase alb_hash
  case "${environment}" in
    aws-dev)
      cluster="startup-devops-baseline-dev"
      application="demo-api-aws-dev"
      kind="Deployment"
      hostname="demo.dev.aureumstack.com"
      rollout_phase="not-applicable"
      analysis_name=""
      analysis_phase="not-applicable"
      alb_hash=""
      ;;
    aws-test)
      cluster="startup-devops-baseline-test"
      application="demo-api-aws-test"
      kind="Rollout"
      hostname="demo.test.aureumstack.com"
      rollout_phase="Healthy"
      analysis_name="demo-api-analysis-fixture"
      analysis_phase="Successful"
      alb_hash="${ALB_HASH}"
      ;;
    aws-prod)
      cluster="startup-devops-baseline-prod"
      application="demo-api-aws-prod"
      kind="Rollout"
      hostname="demo.prod.aureumstack.com"
      rollout_phase="Healthy"
      analysis_name="demo-api-analysis-fixture"
      analysis_phase="Successful"
      alb_hash="${ALB_HASH}"
      ;;
  esac

  local release="${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml"
  local output="${WORK_DIR}/${environment}-${EVIDENCE_ID}.json"
  local image
  image="$(python3 - "${release}" <<'PY'
from pathlib import Path
import json, sys
section = None
values = {}
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    if not raw.startswith(" ") and raw.strip().endswith(":"):
        section = raw.strip()[:-1]
    elif raw.startswith("  ") and ":" in raw.strip():
        key, value = raw.strip().split(":", 1)
        value = value.strip()
        values[(section, key)] = json.loads(value) if value.startswith('"') else value
print(values[("image", "repository")] + "@" + values[("image", "digest")])
PY
)"
  local version="${image}"
  version="$(python3 - "${release}" <<'PY'
from pathlib import Path
import json, sys
section = None
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.startswith(" ") and raw.strip() == "release:":
        section = "release"
    elif section == "release" and raw.startswith("  applicationVersion:"):
        print(json.loads(raw.split(":", 1)[1].strip()))
        break
PY
)"

  ENVIRONMENT="${environment}" RELEASE_FILE="${release}" OUTPUT_FILE="${output}" \
  EVIDENCE_ID="${EVIDENCE_ID}" EVIDENCE_ACTOR="SterlingAureum" \
  RECORDED_AT="${RECORDED_AT}" REPOSITORY_REVISION="${REVISION}" \
  CLUSTER_NAME="${cluster}" ARGO_APPLICATION="${application}" ARGO_REVISION="${REVISION}" \
  WORKLOAD_KIND="${kind}" ROLLOUT_PHASE="${rollout_phase}" \
  ANALYSIS_RUN_NAME="${analysis_name}" ANALYSIS_RUN_PHASE="${analysis_phase}" \
  INGRESS_HOSTNAME="${hostname}" ALB_ACTION_SHA256="${alb_hash}" \
  OBSERVED_IMAGE="${image}" READY_STATUS="ready" READY_DATABASE="ok" \
  OBSERVED_ENVIRONMENT="${environment}" OBSERVED_VERSION="${version}" READY_POD_COUNT="2" \
    "${WRITER}" >/dev/null
  EXPECTED_ENVIRONMENT="${environment}" EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
  EVIDENCE_FILE="${output}" RELEASE_FILE="${release}" \
    "${VALIDATOR}" >/dev/null
}

echo "==> Validating runtime evidence success paths"
for environment in aws-dev aws-test aws-prod; do
  record_fixture "${environment}"
done

echo "==> Rejecting wrong environment, identity, and freshness"
if EXPECTED_ENVIRONMENT="aws-test" EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
  EVIDENCE_FILE="${WORK_DIR}/aws-dev-${EVIDENCE_ID}.json" \
  RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Runtime validator accepted the wrong environment." >&2
  exit 1
fi

cp "${WORK_DIR}/aws-test-${EVIDENCE_ID}.json" "${WORK_DIR}/tampered.json"
python3 - "${WORK_DIR}/tampered.json" <<'PY'
from pathlib import Path
import json, sys
path = Path(sys.argv[1])
document = json.loads(path.read_text())
document["runtime"]["analysisRunPhase"] = "Failed"
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
if EXPECTED_ENVIRONMENT="aws-test" EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
  EVIDENCE_FILE="${WORK_DIR}/tampered.json" \
  RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" \
  "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Runtime validator accepted a failed AnalysisRun." >&2
  exit 1
fi

cp "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" "${WORK_DIR}/stale-release.yaml"
printf '\n# changed after runtime validation\n' >>"${WORK_DIR}/stale-release.yaml"
if EXPECTED_ENVIRONMENT="aws-test" EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
  EVIDENCE_FILE="${WORK_DIR}/aws-test-${EVIDENCE_ID}.json" \
  RELEASE_FILE="${WORK_DIR}/stale-release.yaml" \
  "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Runtime validator accepted a changed release file." >&2
  exit 1
fi

cp "${WORK_DIR}/aws-test-${EVIDENCE_ID}.json" "${WORK_DIR}/expired.json"
python3 - "${WORK_DIR}/expired.json" <<'PY'
from pathlib import Path
import json, sys
path = Path(sys.argv[1])
document = json.loads(path.read_text())
document["runtime"]["recordedAt"] = "2000-01-01T00:00:00Z"
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
if EXPECTED_ENVIRONMENT="aws-test" EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
  EVIDENCE_FILE="${WORK_DIR}/expired.json" \
  RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" \
  "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Runtime validator accepted evidence outside its freshness window." >&2
  exit 1
fi

echo "demo-api runtime evidence behavior passed."
