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
module = root / "infra" / "terraform" / "aws" / "modules" / "eks" / "main.tf"
runtime = root / "scripts" / "validate-eks-network-policy-aws.sh"
module_readme = (
    root / "infra" / "terraform" / "aws" / "modules" / "eks" / "README.md"
)

required_files = [module, runtime, module_readme]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(
        "EKS network-policy files are missing: " + ", ".join(missing)
    )


def require(path: Path, values: list[str], description: str) -> None:
    content = path.read_text()
    for value in values:
        if value not in content:
            raise SystemExit(
                f"{path.relative_to(root)}: {description} is missing: {value}"
            )


require(
    module,
    [
        'for_each = toset(["vpc-cni", "kube-proxy"])',
        'configuration_values = each.value == "vpc-cni" ? jsonencode({',
        'enableNetworkPolicy = "true"',
    ],
    "address-preserving VPC CNI NetworkPolicy configuration",
)

require(
    runtime,
    [
        'ADDON_NAME="vpc-cni"',
        "--enable-network-policy=true",
        "NETWORK_POLICY_ENFORCING_MODE",
        "policyendpoints.networking.k8s.aws",
        "kind: Deployment",
        "kind: NetworkPolicy",
        "Verifying baseline connectivity",
        "Verifying default-deny enforcement",
        "Verifying explicit allow recovery",
        "network-policy enforcement validation passed.",
    ],
    "isolated runtime enforcement matrix",
)

runtime_content = runtime.read_text()
if "startup-apps" in runtime_content or "data-platform" in runtime_content:
    raise SystemExit(
        f"{runtime.relative_to(root)}: checkpoint 1 must not target business "
        "namespaces."
    )
if runtime_content.count("kind: Deployment") < 2:
    raise SystemExit(
        f"{runtime.relative_to(root)}: both test endpoints must be managed by "
        "Deployments."
    )

require(
    module_readme,
    [
        "VPC CNI managed add-on explicitly enables standard Kubernetes",
        "node agent remains in standard mode",
        "validated in an isolated namespace",
    ],
    "NetworkPolicy enforcement operating model",
)
PY

echo "EKS network-policy contract validation passed."
