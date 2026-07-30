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
policy_dir = (
    root
    / "platform"
    / "security"
    / "admission-policies"
    / "application-workloads"
)
pod_policy = policy_dir / "pod-policy.yaml"
pod_binding = policy_dir / "pod-binding.yaml"
workload_policy = policy_dir / "workload-policy.yaml"
workload_binding = policy_dir / "workload-binding.yaml"
aws_app = (
    root
    / "clusters"
    / "aws-dev"
    / "platform"
    / "application-admission-policies.yaml"
)
runtime_validation = (
    root / "scripts" / "validate-application-admission-policies-aws.sh"
)

required_files = [
    pod_policy,
    pod_binding,
    workload_policy,
    workload_binding,
    aws_app,
    runtime_validation,
]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(
        "Application admission-policy files are missing: " + ", ".join(missing)
    )


def require(path: Path, values: list[str], description: str) -> None:
    content = path.read_text()
    for value in values:
        if value not in content:
            raise SystemExit(
                f"{path.relative_to(root)}: {description} is missing: {value}"
            )


for path in [pod_policy, workload_policy]:
    require(
        path,
        [
            "apiVersion: admissionregistration.k8s.io/v1",
            "kind: ValidatingAdmissionPolicy",
            "failurePolicy: Fail",
            'apiVersions: ["v1"]',
            'operations: ["CREATE", "UPDATE"]',
            "container.image.matches('^.+@sha256:[0-9a-f]{64}$')",
            "expression: variables.containers.map(container, container.?resources)",
            "expression: variables.initContainers.map(container, container.?resources)",
            "resources.?requests[?'cpu'].hasValue()",
            "resources.?requests[?'memory'].hasValue()",
            "resources.?limits[?'cpu'].hasValue()",
            "resources.?limits[?'memory'].hasValue()",
            "reason: Invalid",
        ],
        "fail-closed immutable-image and resource contract",
    )

require(
    pod_policy,
    [
        "startup-application-pods.security.startup.dev",
        'apiGroups: [""]',
        'resources: ["pods"]',
        "expression: object.spec.containers",
        "expression: object.spec.?initContainers.orValue([])",
        "variables.containers.all",
        "variables.initContainers.all",
    ],
    "Pod admission policy",
)
require(
    workload_policy,
    [
        "startup-application-workloads.security.startup.dev",
        'apiGroups: ["apps"]',
        'resources: ["deployments", "statefulsets", "daemonsets"]',
        'apiGroups: ["batch"]',
        'resources: ["jobs"]',
        "expression: object.spec.template.spec.containers",
        "expression: object.spec.template.spec.?initContainers.orValue([])",
        "variables.containers.all",
        "variables.initContainers.all",
    ],
    "controller-template admission policy",
)

for path, policy_name in [
    (pod_binding, "startup-application-pods.security.startup.dev"),
    (workload_binding, "startup-application-workloads.security.startup.dev"),
]:
    require(
        path,
        [
            "apiVersion: admissionregistration.k8s.io/v1",
            "kind: ValidatingAdmissionPolicyBinding",
            f"policyName: {policy_name}",
            "validationActions:",
            "- Deny",
            "- Audit",
            "namespaceSelector:",
            "platform.startup.dev/tier: application",
        ],
        "application-tier deny-and-audit binding",
    )

require(
    aws_app,
    [
        "name: application-admission-policies-aws-dev",
        'argocd.argoproj.io/sync-wave: "-4"',
        "targetRevision: feature/v0.8-production-security-baseline",
        "path: platform/security/admission-policies/application-workloads",
        "namespace: startup-apps",
        "ServerSideApply=true",
    ],
    "aws-dev admission-policy Application",
)

local_platform = root / "clusters" / "local" / "platform"
if any(
    path.name == "application-admission-policies.yaml"
    for path in local_platform.glob("*.yaml")
):
    raise SystemExit(
        "Strict digest admission must remain disabled for tag-loaded local images."
    )
PY

echo "application admission-policy contract validation passed."
