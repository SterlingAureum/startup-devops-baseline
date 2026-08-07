#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in helm python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

for environment in aws-dev aws-test aws-prod; do
  helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/${environment}.yaml" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml" \
    >"${WORK_DIR}/demo-api-${environment}.yaml"
done

python3 - "${WORK_DIR}" <<'PY'
from pathlib import Path
import re
import sys

work_dir = Path(sys.argv[1])
expected_kinds = {
    "aws-dev": "Deployment",
    "aws-test": "Rollout",
    "aws-prod": "Rollout",
}


def indented_mapping(document, section):
    match = re.search(
        rf"(?m)^      {re.escape(section)}:\s*$\n((?:^        .*$\n?)*)",
        document,
    )
    if not match:
        return {}

    values = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().removeprefix("- ")
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"')
    return values

for environment, expected_kind in expected_kinds.items():
    path = work_dir / f"demo-api-{environment}.yaml"
    documents = re.split(r"(?m)^---\s*$", path.read_text())
    workloads = [
        document
        for document in documents
        if f"kind: {expected_kind}\n" in document
        and re.search(r"(?m)^  name: demo-api$", document)
    ]
    if len(workloads) != 1:
        raise SystemExit(
            f"{environment}: expected exactly one demo-api {expected_kind}, "
            f"found {len(workloads)}"
        )

    workload = workloads[0]
    actual_node_selector = indented_mapping(workload, "nodeSelector")
    expected_node_selector = {
        "capacity-tier": "on-demand",
        "workload": "application",
    }
    if actual_node_selector != expected_node_selector:
        raise SystemExit(
            f"{environment}: invalid nodeSelector: {actual_node_selector}"
        )

    actual_toleration = indented_mapping(workload, "tolerations")
    expected_toleration = {
        "effect": "NoSchedule",
        "key": "dedicated",
        "operator": "Equal",
        "value": "application",
    }
    if actual_toleration != expected_toleration:
        raise SystemExit(
            f"{environment}: invalid toleration: {actual_toleration}"
        )

    if "application-spot" in workload or "application-spot-fis" in workload:
        raise SystemExit(
            f"{environment}: normal demo-api workloads must not opt into Spot tiers"
        )

print("demo-api AWS application-capacity scheduling validation passed.")
PY
