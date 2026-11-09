#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path(
    "delivery/contracts/v0.11.9.2.2.3.3.3.1-rendered-identity-projection-repair.json"
).read_text())

assert contract["version"] == "v0.11.9.2.2.3.3.3.1"
assert contract["predecessor"] == "v0.11.9.2.2.3.3.3"
assert contract["failure"]["runtimeManifestInvalid"] is False
assert contract["repair"] == {
    "containerProjectionValidatedStructurally": True,
    "analysisProjectionValidatedSeparately": True,
    "analysisStepCountDerivedFromRenderedBindings": True,
    "deploymentAnalysisProjectionForbidden": True,
    "globalAnnotationStringCountRemoved": True,
}
assert contract["rolloutTemplateChanged"] is False
assert contract["imageIdentityChanged"] is False
assert contract["rolloutRevisionChangeExpected"] is False
assert contract["clusterMutationDuringValidation"] is False
assert contract["awsMutationDuringValidation"] is False

historical = Path(
    "scripts/validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh"
).read_text()
assert "check-demo-api-rendered-identity-projection.py" in historical
assert "expected_annotation_count = 3" not in historical
assert "is not rendered exactly once" not in historical

checker = Path("scripts/check-demo-api-rendered-identity-projection.py").read_text()
for marker in (
    "def binding_count",
    "def validate_environment_projection",
    "def validate_rollout_analysis_projection",
    "def validate_no_analysis_projection",
    '"expected-release-id"',
    '"source-commit"',
    '"image-digest"',
):
    assert marker in checker, marker
PY

write_environment_bindings() {
  cat <<'EOF'
        - name: PLATFORM_RELEASE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['platform.startup.dev/release-id']
        - name: PLATFORM_SOURCE_COMMIT
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['platform.startup.dev/source-commit']
        - name: CONTAINER_IMAGE_DIGEST
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['platform.startup.dev/image-digest']
EOF
}

write_analysis_bindings() {
  cat <<'EOF'
      - name: expected-release-id
        valueFrom:
          fieldRef:
            fieldPath: metadata.annotations['platform.startup.dev/release-id']
      - name: image-digest
        valueFrom:
          fieldRef:
            fieldPath: metadata.annotations['platform.startup.dev/image-digest']
      - name: source-commit
        valueFrom:
          fieldRef:
            fieldPath: metadata.annotations['platform.startup.dev/source-commit']
EOF
}

{
  printf '%s\n' 'apiVersion: argoproj.io/v1alpha1' 'kind: Rollout' 'spec:' '  strategy:'
  write_analysis_bindings
  write_analysis_bindings
  printf '%s\n' '  template:' '    spec:' '      containers:' '      - name: demo-api' '        env:'
  write_environment_bindings
} >"${WORK_DIR}/rollout.yaml"

{
  printf '%s\n' 'apiVersion: apps/v1' 'kind: Deployment' 'spec:' '  template:' '    spec:' \
    '      containers:' '      - name: demo-api' '        env:'
  write_environment_bindings
} >"${WORK_DIR}/deployment.yaml"

python3 scripts/check-demo-api-rendered-identity-projection.py \
  --rollout "${WORK_DIR}/rollout.yaml" \
  --deployment "${WORK_DIR}/deployment.yaml"

cp "${WORK_DIR}/rollout.yaml" "${WORK_DIR}/duplicate-environment.yaml"
write_environment_bindings >>"${WORK_DIR}/duplicate-environment.yaml"
if python3 scripts/check-demo-api-rendered-identity-projection.py \
  --rollout "${WORK_DIR}/duplicate-environment.yaml" \
  --deployment "${WORK_DIR}/deployment.yaml" >/dev/null 2>&1; then
  echo "Duplicate container identity projection was accepted" >&2
  exit 1
fi

python3 - "${WORK_DIR}/rollout.yaml" "${WORK_DIR}/missing-analysis.yaml" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text()
binding = """      - name: source-commit
        valueFrom:
          fieldRef:
            fieldPath: metadata.annotations['platform.startup.dev/source-commit']
"""
replacement = """      - name: source-commit
        value: ""
"""
assert source.count(binding) == 2
Path(sys.argv[2]).write_text(source.replace(binding, replacement, 1))
PY

if python3 scripts/check-demo-api-rendered-identity-projection.py \
  --rollout "${WORK_DIR}/missing-analysis.yaml" \
  --deployment "${WORK_DIR}/deployment.yaml" >/dev/null 2>&1; then
  echo "Missing AnalysisRun source-commit binding was accepted" >&2
  exit 1
fi

cp "${WORK_DIR}/deployment.yaml" "${WORK_DIR}/deployment-with-analysis.yaml"
write_analysis_bindings >>"${WORK_DIR}/deployment-with-analysis.yaml"
if python3 scripts/check-demo-api-rendered-identity-projection.py \
  --rollout "${WORK_DIR}/rollout.yaml" \
  --deployment "${WORK_DIR}/deployment-with-analysis.yaml" >/dev/null 2>&1; then
  echo "Deployment AnalysisRun binding was accepted" >&2
  exit 1
fi

python3 -m py_compile scripts/check-demo-api-rendered-identity-projection.py
bash -n scripts/validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh
bash -n scripts/validate-v0.11.9.2.2.3.3.3.1-rendered-identity-projection-repair.sh

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh \
    scripts/validate-v0.11.9.2.2.3.3.3.1-rendered-identity-projection-repair.sh
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.2.2.3.3.3.1 rendered identity projection repair passed; no live operation was executed."
