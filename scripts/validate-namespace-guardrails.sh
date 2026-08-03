#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])

startup_dir = (
    root / "platform" / "security" / "namespace-guardrails" / "startup-apps"
)
startup_namespace = startup_dir / "namespace.yaml"
startup_quota = startup_dir / "resource-quota.yaml"
startup_limits = startup_dir / "limit-range.yaml"
data_dir = root / "clusters" / "aws-dev" / "data-platform" / "postgresql"
data_namespace = data_dir / "namespace.yaml"
data_quota = data_dir / "resource-quota.yaml"
data_limits = data_dir / "limit-range.yaml"
local_app = root / "clusters" / "local" / "platform" / "namespace-guardrails.yaml"
aws_app = root / "clusters" / "aws-dev" / "platform" / "namespace-guardrails.yaml"
aws_demo_app = root / "clusters" / "aws-dev" / "platform" / "demo-api.yaml"
aws_postgres_app = (
    root / "clusters" / "aws-dev" / "platform" / "postgresql-baseline.yaml"
)

required_files = [
    startup_namespace,
    startup_quota,
    startup_limits,
    data_namespace,
    data_quota,
    data_limits,
    local_app,
    aws_app,
]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit("Namespace guardrail files are missing: " + ", ".join(missing))


def require(path: Path, values: list[str], description: str) -> None:
    content = path.read_text()
    for value in values:
        if value not in content:
            raise SystemExit(
                f"{path.relative_to(root)}: {description} is missing: {value}"
            )


require(
    startup_namespace,
    [
        "name: startup-apps",
        "security.startup.dev/admission-guardrails: enabled",
        "pod-security.kubernetes.io/enforce: restricted",
        "pod-security.kubernetes.io/enforce-version: v1.30",
        "pod-security.kubernetes.io/warn: restricted",
        "pod-security.kubernetes.io/audit: restricted",
    ],
    "startup-apps Pod Security Admission contract",
)
require(
    data_namespace,
    [
        "name: data-platform",
        "security.startup.dev/admission-guardrails: enabled",
        "pod-security.kubernetes.io/enforce: baseline",
        "pod-security.kubernetes.io/enforce-version: v1.30",
        "pod-security.kubernetes.io/warn: restricted",
        "pod-security.kubernetes.io/audit: restricted",
    ],
    "data-platform staged Pod Security Admission contract",
)

for path, namespace in [
    (startup_quota, "startup-apps"),
    (data_quota, "data-platform"),
]:
    require(
        path,
        [
            "kind: ResourceQuota",
            f"name: {namespace}",
            f"namespace: {namespace}",
            "requests.cpu:",
            "requests.memory:",
            "limits.cpu:",
            "limits.memory:",
            "pods:",
            "services:",
            "secrets:",
            "persistentvolumeclaims:",
            "requests.storage:",
        ],
        f"{namespace} ResourceQuota contract",
    )

for path, namespace in [
    (startup_limits, "startup-apps"),
    (data_limits, "data-platform"),
]:
    require(
        path,
        [
            "kind: LimitRange",
            f"namespace: {namespace}",
            "type: Container",
            "defaultRequest:",
            "default:",
            "min:",
            "max:",
            "cpu:",
            "memory:",
        ],
        f"{namespace} LimitRange contract",
    )

require(
    local_app,
    [
        "name: namespace-guardrails",
        'argocd.argoproj.io/sync-wave: "-5"',
        "targetRevision: HEAD",
        "path: platform/security/namespace-guardrails/startup-apps",
        "namespace: startup-apps",
        "ServerSideApply=true",
    ],
    "local namespace guardrail Application",
)
require(
    aws_app,
    [
        "name: namespace-guardrails-aws-dev",
        'argocd.argoproj.io/sync-wave: "-5"',
        "targetRevision: feature/v0.8-production-security-baseline",
        "path: platform/security/namespace-guardrails/startup-apps",
        "namespace: startup-apps",
        "ServerSideApply=true",
    ],
    "aws-dev namespace guardrail Application",
)

for path in [aws_demo_app, aws_postgres_app]:
    require(
        path,
        ["targetRevision: feature/v0.8-production-security-baseline"],
        "v0.8 feature-branch runtime validation source",
    )
PY

echo "namespace guardrail contract validation passed."
