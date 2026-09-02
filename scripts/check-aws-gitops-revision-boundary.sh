#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_DEV_GIT_TARGET_REVISION="${EXPECTED_DEV_GIT_TARGET_REVISION:-feature/v0.11-observability-sre-baseline}"
EXPECTED_TEST_GIT_TARGET_REVISION="${EXPECTED_TEST_GIT_TARGET_REVISION:-main}"
EXPECTED_PROD_GIT_TARGET_REVISION="${EXPECTED_PROD_GIT_TARGET_REVISION:-main}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

if command -v kustomize >/dev/null 2>&1; then
  render() { kustomize build "$1"; }
elif command -v kubectl >/dev/null 2>&1; then
  render() { kubectl kustomize "$1"; }
else
  echo "kustomize or kubectl is required for AWS revision-boundary rendering" >&2
  exit 1
fi

render "${ROOT_DIR}/clusters/aws/overlays/dev" >"${WORK_DIR}/dev.yaml"
render "${ROOT_DIR}/clusters/aws/overlays/test" >"${WORK_DIR}/test.yaml"
render "${ROOT_DIR}/clusters/aws/overlays/prod" >"${WORK_DIR}/prod.yaml"

python3 - \
  "${WORK_DIR}/dev.yaml" "${EXPECTED_DEV_GIT_TARGET_REVISION}" 9 \
  "${WORK_DIR}/test.yaml" "${EXPECTED_TEST_GIT_TARGET_REVISION}" 9 \
  "${WORK_DIR}/prod.yaml" "${EXPECTED_PROD_GIT_TARGET_REVISION}" 8 <<'PY'
from pathlib import Path
import re
import sys

REPOSITORY = "https://github.com/SterlingAureum/startup-devops-baseline.git"
EXTERNAL_CHARTS = {
    "argo-rollouts": "2.41.1",
    "aws-load-balancer-controller": "1.14.0",
    "plugin-barman-cloud": "0.7.0",
    "cert-manager": "v1.21.0",
    "cloudnative-pg": "0.29.0",
    "external-secrets": "2.8.0",
    "karpenter": "1.14.0",
    "karpenter-crd": "1.14.0",
    "kube-prometheus-stack": "88.5.0",
}

def scalar(document: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s+{re.escape(key)}:\s*([^#\n]+?)\s*$", document)
    return match.group(1).strip(' "\'') if match else None

def validate(path: str, expected_git_revision: str, expected_git_count: int) -> None:
    applications = []
    for document in re.split(r"(?m)^---\s*$", Path(path).read_text()):
        if not re.search(r"(?m)^kind:\s*Application\s*$", document):
            continue
        applications.append({
            "name": scalar(document, "name"),
            "repo": scalar(document, "repoURL"),
            "chart": scalar(document, "chart"),
            "revision": scalar(document, "targetRevision"),
        })
    git_apps = [item for item in applications if item["repo"] == REPOSITORY]
    if len(git_apps) != expected_git_count:
        raise SystemExit(f"{path}: expected {expected_git_count} same-repository Applications, found {len(git_apps)}")
    wrong = [item for item in git_apps if item["revision"] != expected_git_revision]
    if wrong:
        raise SystemExit(f"{path}: same-repository revision mismatch: {wrong}")
    external = [item for item in applications if item["chart"]]
    for item in external:
        expected = EXTERNAL_CHARTS.get(item["chart"])
        if expected is None or item["revision"] != expected:
            raise SystemExit(
                f"{path}: external Chart identity/revision changed: "
                f"application={item['name']}, chart={item['chart']}, "
                f"expected={expected}, actual={item['revision']}"
            )

arguments = sys.argv[1:]
for offset in range(0, len(arguments), 3):
    validate(arguments[offset], arguments[offset + 1], int(arguments[offset + 2]))

print("AWS dev/test/prod same-repository and external-Chart revision boundaries passed.")
PY
