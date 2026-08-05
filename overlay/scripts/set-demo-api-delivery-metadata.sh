#!/usr/bin/env bash
set -Eeuo pipefail

VALUES_FILE="${VALUES_FILE:-apps/demo-api/helm/values/releases/aws-dev.yaml}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-}"
SOURCE_COMMIT="${SOURCE_COMMIT:-}"
WORKFLOW_RUN_ID="${WORKFLOW_RUN_ID:-}"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

if [[ ! -f "${VALUES_FILE}" ]]; then
  echo "Promotion values file not found: ${VALUES_FILE}" >&2
  exit 1
fi

if [[ -z "${SOURCE_REPOSITORY}" || -z "${WORKFLOW_RUN_ID}" ]]; then
  echo "SOURCE_REPOSITORY and WORKFLOW_RUN_ID are required." >&2
  exit 1
fi

if [[ ! "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "SOURCE_COMMIT must be a full lowercase Git commit SHA." >&2
  exit 1
fi

python3 - \
  "${VALUES_FILE}" \
  "${SOURCE_REPOSITORY}" \
  "${SOURCE_COMMIT}" \
  "${WORKFLOW_RUN_ID}" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
updates = {
    "sourceRepository": sys.argv[2],
    "sourceCommit": sys.argv[3],
    "workflowRunId": sys.argv[4],
}
lines = path.read_text().splitlines()

start = next(
    (
        index
        for index, line in enumerate(lines)
        if line == "delivery:"
    ),
    None,
)

if start is None:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("delivery:")
    for key, value in updates.items():
        lines.append(f"  {key}: {json.dumps(value)}")
else:
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith((" ", "#")):
            end = index
            break

    found = set()
    body = []
    for line in lines[start + 1:end]:
        stripped = line.strip()
        key = stripped.split(":", 1)[0] if ":" in stripped else ""
        if key in updates:
            body.append(f"  {key}: {json.dumps(updates[key])}")
            found.add(key)
        else:
            body.append(line)

    for key, value in updates.items():
        if key not in found:
            body.append(f"  {key}: {json.dumps(value)}")

    lines = lines[:start + 1] + body + lines[end:]

path.write_text("\n".join(lines) + "\n")
PY

echo "Updated ${VALUES_FILE} delivery metadata:"
echo "  source=${SOURCE_REPOSITORY}@${SOURCE_COMMIT}"
echo "  workflow_run_id=${WORKFLOW_RUN_ID}"
