#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY="${GITHUB_REPOSITORY:-SterlingAureum/startup-devops-baseline}"
ENVIRONMENT="${ENVIRONMENT:-aws-dev}"
INTERRUPTED_RUN_ID="${INTERRUPTED_RUN_ID:-}"
RESUMED_RUN_ID="${RESUMED_RUN_ID:-}"
OUTPUT_FILE="${OUTPUT_FILE:-}"

for command in gh jq python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

case "${ENVIRONMENT}" in
  aws-dev|aws-test) ;;
  *)
    echo "ENVIRONMENT must be aws-dev or aws-test." >&2
    exit 1
    ;;
esac
for value in "${INTERRUPTED_RUN_ID}" "${RESUMED_RUN_ID}"; do
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || {
    echo "INTERRUPTED_RUN_ID and RESUMED_RUN_ID must be positive GitHub workflow run IDs." >&2
    exit 1
  }
done
[[ "${INTERRUPTED_RUN_ID}" != "${RESUMED_RUN_ID}" ]] || {
  echo "Interrupted and resumed workflow run IDs must differ." >&2
  exit 1
}
[[ -n "${OUTPUT_FILE}" && "${OUTPUT_FILE}" == /* ]] || {
  echo "OUTPUT_FILE must be an absolute path outside the repository." >&2
  exit 1
}
case "${OUTPUT_FILE}" in
  "${ROOT_DIR}"|"${ROOT_DIR}"/*)
    echo "Runner isolation output is an operator record and must stay outside the repository." >&2
    exit 1
    ;;
esac

work_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

gh api "repos/${REPOSITORY}/actions/runs/${INTERRUPTED_RUN_ID}" > "${work_dir}/interrupted-run.json"
gh api "repos/${REPOSITORY}/actions/runs/${INTERRUPTED_RUN_ID}/jobs?per_page=100" > "${work_dir}/interrupted-jobs.json"
gh api "repos/${REPOSITORY}/actions/runs/${RESUMED_RUN_ID}" > "${work_dir}/resumed-run.json"
gh api "repos/${REPOSITORY}/actions/runs/${RESUMED_RUN_ID}/jobs?per_page=100" > "${work_dir}/resumed-jobs.json"
gh api "repos/${REPOSITORY}/actions/runners?per_page=100" > "${work_dir}/registered-runners.json"

python3 "${ROOT_DIR}/scripts/validate-demo-api-runner-isolation.py" \
  --repository "${REPOSITORY}" \
  --environment "${ENVIRONMENT}" \
  --interrupted-run-id "${INTERRUPTED_RUN_ID}" \
  --resumed-run-id "${RESUMED_RUN_ID}" \
  --interrupted-run "${work_dir}/interrupted-run.json" \
  --interrupted-jobs "${work_dir}/interrupted-jobs.json" \
  --resumed-run "${work_dir}/resumed-run.json" \
  --resumed-jobs "${work_dir}/resumed-jobs.json" \
  --registered-runners "${work_dir}/registered-runners.json" \
  --output "${OUTPUT_FILE}"

jq '{
  status,
  environment,
  automaticUnregistrationVerified,
  interrupted: {
    runId: .interrupted.runId,
    runAttempt: .interrupted.runAttempt,
    runnerId: .interrupted.runnerId,
    runnerName: .interrupted.runnerName,
    jobConclusion: .interrupted.jobConclusion
  },
  resumed: {
    runId: .resumed.runId,
    runAttempt: .resumed.runAttempt,
    runnerId: .resumed.runnerId,
    runnerName: .resumed.runnerName,
    jobConclusion: .resumed.jobConclusion
  }
}' "${OUTPUT_FILE}"
