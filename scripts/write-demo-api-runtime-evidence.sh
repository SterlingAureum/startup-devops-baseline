#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${ENVIRONMENT:-}"
RELEASE_FILE="${RELEASE_FILE:-}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
EVIDENCE_ID="${EVIDENCE_ID:-}"
EVIDENCE_ACTOR="${EVIDENCE_ACTOR:-}"
RECORDED_AT="${RECORDED_AT:-}"
REPOSITORY_REVISION="${REPOSITORY_REVISION:-}"
CLUSTER_NAME="${CLUSTER_NAME:-}"
ARGO_APPLICATION="${ARGO_APPLICATION:-}"
ARGO_REVISION="${ARGO_REVISION:-}"
WORKLOAD_KIND="${WORKLOAD_KIND:-}"
WORKLOAD_NAME="${WORKLOAD_NAME:-demo-api}"
ROLLOUT_PHASE="${ROLLOUT_PHASE:-not-applicable}"
ANALYSIS_RUN_NAME="${ANALYSIS_RUN_NAME:-}"
ANALYSIS_RUN_PHASE="${ANALYSIS_RUN_PHASE:-not-applicable}"
INGRESS_HOSTNAME="${INGRESS_HOSTNAME:-}"
ALB_ACTION_SHA256="${ALB_ACTION_SHA256:-}"
OBSERVED_IMAGE="${OBSERVED_IMAGE:-}"
READY_STATUS="${READY_STATUS:-}"
READY_DATABASE="${READY_DATABASE:-}"
OBSERVED_ENVIRONMENT="${OBSERVED_ENVIRONMENT:-}"
OBSERVED_VERSION="${OBSERVED_VERSION:-}"
READY_POD_COUNT="${READY_POD_COUNT:-}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"

case "${ENVIRONMENT}" in
  aws-dev|aws-test|aws-prod) ;;
  *)
    echo "Runtime evidence environment must be aws-dev, aws-test, or aws-prod." >&2
    exit 1
    ;;
esac

RELEASE_FILE="${RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${ENVIRONMENT}.yaml}"
OUTPUT_FILE="${OUTPUT_FILE:-${ROOT_DIR}/evidence/demo-api/runtime/${ENVIRONMENT}/${EVIDENCE_ID}.json}"

python3 - \
  "${RELEASE_FILE}" "${OUTPUT_FILE}" "${ENVIRONMENT}" "${EVIDENCE_ID}" \
  "${EVIDENCE_ACTOR}" "${RECORDED_AT}" "${REPOSITORY_REVISION}" \
  "${CLUSTER_NAME}" "${ARGO_APPLICATION}" "${ARGO_REVISION}" \
  "${WORKLOAD_KIND}" "${WORKLOAD_NAME}" "${ROLLOUT_PHASE}" \
  "${ANALYSIS_RUN_NAME}" "${ANALYSIS_RUN_PHASE}" "${INGRESS_HOSTNAME}" \
  "${ALB_ACTION_SHA256}" "${OBSERVED_IMAGE}" "${READY_STATUS}" \
  "${READY_DATABASE}" "${OBSERVED_ENVIRONMENT}" "${OBSERVED_VERSION}" \
  "${READY_POD_COUNT}" "${EXPECTED_IMAGE_REPOSITORY}" \
  "${EXPECTED_SOURCE_REPOSITORY}" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys

(
    release_name, output_name, environment, evidence_id, actor, recorded_at,
    repository_revision, cluster_name, argo_application, argo_revision,
    workload_kind, workload_name, rollout_phase, analysis_name, analysis_phase,
    ingress_hostname, alb_action_sha256, observed_image, ready_status,
    ready_database, observed_environment, observed_version, ready_pod_count,
    expected_image_repository, expected_source_repository,
) = sys.argv[1:]

release_path = Path(release_name)
output_path = Path(output_name)


def scalar(raw):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def release_values(path):
    values = {}
    section = None
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            continue
        if indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            field = (section, key)
            if field in values:
                raise SystemExit(f"{path}:{number}: duplicate {section}.{key}")
            values[field] = scalar(value)
            continue
        raise SystemExit(f"{path}:{number}: unsupported release values structure")
    return values


required = {
    ("image", "repository"), ("image", "tag"), ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"), ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
}
if not release_path.is_file():
    raise SystemExit(f"Release file not found: {release_path}")
values = release_values(release_path)
if set(values) != required:
    raise SystemExit("Release values do not satisfy the isolated release schema.")
if not re.fullmatch(r"[0-9]{14}", evidence_id):
    raise SystemExit("EVIDENCE_ID must use UTC YYYYMMDDHHMMSS digits.")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", actor):
    raise SystemExit("EVIDENCE_ACTOR must be a valid GitHub login.")
if not re.fullmatch(r"[0-9a-f]{40}", repository_revision):
    raise SystemExit("REPOSITORY_REVISION must be a full lowercase commit SHA.")
if argo_revision != repository_revision:
    raise SystemExit("Argo CD revision must equal the validated repository revision.")
if not re.fullmatch(r"[1-9][0-9]*", ready_pod_count):
    raise SystemExit("READY_POD_COUNT must be a positive integer.")

repository = values[("image", "repository")]
tag = values[("image", "tag")]
digest = values[("image", "digest")]
version = values[("release", "applicationVersion")]
source_repository = values[("delivery", "sourceRepository")]
source_commit = values[("delivery", "sourceCommit")]
build_run_id = values[("delivery", "workflowRunId")]
if repository != expected_image_repository or source_repository != expected_source_repository:
    raise SystemExit("Runtime evidence rejected an unexpected repository identity.")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    raise SystemExit("Runtime evidence requires a valid immutable image digest.")
if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
    raise SystemExit("Runtime evidence requires a full source commit.")
if tag != f"sha-{source_commit[:7]}" or version != tag:
    raise SystemExit("Runtime evidence rejected inconsistent readable identities.")
if not build_run_id:
    raise SystemExit("Runtime evidence requires the original build workflow identity.")
if observed_image != f"{repository}@{digest}":
    raise SystemExit("Observed Pod image differs from the release digest.")
if ready_status != "ready" or ready_database != "ok":
    raise SystemExit("Runtime readiness or database verification did not pass.")
if observed_environment != environment or observed_version != version:
    raise SystemExit("Runtime /version identity differs from the release environment.")

expected = {
    "aws-dev": ("startup-devops-baseline-dev", "demo-api-aws-dev", "Deployment", "demo.dev.aureumstack.com"),
    "aws-test": ("startup-devops-baseline-test", "demo-api-aws-test", "Rollout", "demo.test.aureumstack.com"),
    "aws-prod": ("startup-devops-baseline-prod", "demo-api-aws-prod", "Rollout", "demo.prod.aureumstack.com"),
}[environment]
if (cluster_name, argo_application, workload_kind, ingress_hostname) != expected:
    raise SystemExit("Runtime evidence contains an unexpected environment resource identity.")
if workload_name != "demo-api":
    raise SystemExit("Runtime evidence contains an unexpected workload name.")

checks = [
    "argocd-synced-healthy", "release-annotations-match",
    "all-pods-ready", "immutable-pod-image-match", "https-health",
    "https-ready-database", "https-version-identity",
]
if environment == "aws-dev":
    if rollout_phase != "not-applicable" or analysis_name or analysis_phase != "not-applicable" or alb_action_sha256:
        raise SystemExit("aws-dev runtime evidence must retain the Deployment baseline.")
else:
    if rollout_phase != "Healthy" or analysis_phase != "Successful" or not analysis_name:
        raise SystemExit("Progressive-delivery evidence requires a healthy Rollout and successful AnalysisRun.")
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", analysis_name):
        raise SystemExit("Progressive-delivery evidence contains an invalid AnalysisRun name.")
    if not re.fullmatch(r"[0-9a-f]{64}", alb_action_sha256):
        raise SystemExit("Progressive-delivery evidence requires the completed ALB action digest.")
    checks.extend([
        "rollout-healthy", "analysis-run-successful",
        "analysis-release-identity-match", "alb-stable-weight-100",
    ])

if recorded_at:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", recorded_at):
        raise SystemExit("RECORDED_AT must use UTC YYYY-MM-DDTHH:MM:SSZ.")
    datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
else:
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

document = {
    "schemaVersion": "v0.9.5",
    "application": "demo-api",
    "environment": environment,
    "status": "passed",
    "release": {
        "path": f"apps/demo-api/helm/values/releases/{environment}.yaml",
        "sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        "imageRepository": repository,
        "imageTag": tag,
        "imageDigest": digest,
        "applicationVersion": version,
        "sourceRepository": source_repository,
        "sourceCommit": source_commit,
        "buildWorkflowRunId": build_run_id,
    },
    "runtime": {
        "mode": "aws-runtime-verification",
        "evidenceId": evidence_id,
        "actor": actor,
        "recordedAt": recorded_at,
        "repositoryRevision": repository_revision,
        "clusterName": cluster_name,
        "argoApplication": argo_application,
        "argoRevision": argo_revision,
        "namespace": "startup-apps",
        "workloadKind": workload_kind,
        "workloadName": workload_name,
        "rolloutPhase": rollout_phase,
        "analysisRunName": analysis_name,
        "analysisRunPhase": analysis_phase,
        "ingressHostname": ingress_hostname,
        "albActionSha256": alb_action_sha256,
        "observedImage": observed_image,
        "readyPodCount": int(ready_pod_count),
        "checks": checks,
    },
}
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
print(f"Recorded demo-api AWS runtime evidence: {output_path}")
PY
