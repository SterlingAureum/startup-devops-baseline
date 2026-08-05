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
policy = (
    root
    / "clusters"
    / "aws-dev"
    / "security"
    / "network-policies"
    / "startup-apps"
    / "policies.yaml"
)
application = (
    root
    / "clusters"
    / "aws-dev"
    / "platform"
    / "startup-apps-network-policy.yaml"
)
runtime = root / "scripts" / "validate-startup-apps-network-policy-aws.sh"
archive = root / "docs" / "archive" / "V0.8.2_NETWORK_POLICY_ENFORCEMENT.md"

required_files = [policy, application, runtime, archive]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(
        "startup-apps NetworkPolicy files are missing: " + ", ".join(missing)
    )


def require(path: Path, values: list[str], description: str) -> None:
    content = path.read_text()
    for value in values:
        if value not in content:
            raise SystemExit(
                f"{path.relative_to(root)}: {description} is missing: {value}"
            )


require(
    policy,
    [
        "name: default-deny",
        "podSelector: {}",
        "name: allow-dns-egress",
        "kubernetes.io/metadata.name: kube-system",
        "k8s-app: kube-dns",
        "name: allow-alb-to-demo-api",
        "cidr: 10.20.0.0/24",
        "cidr: 10.20.1.0/24",
        "name: allow-demo-api-to-postgresql",
        "kubernetes.io/metadata.name: data-platform",
        "platform.startup.dev/tier: data",
        "cnpg.io/cluster: postgresql-baseline",
        "port: 5432",
    ],
    "application isolation policy contract",
)

policy_content = policy.read_text()
if policy_content.count("kind: NetworkPolicy") != 4:
    raise SystemExit(
        f"{policy.relative_to(root)}: expected exactly four NetworkPolicy objects."
    )
if "cidr: 10.20.0.0/16" in policy_content:
    raise SystemExit(
        f"{policy.relative_to(root)}: ALB ingress must not allow the whole VPC."
    )
if "namespace: data-platform" in policy_content:
    raise SystemExit(
        f"{policy.relative_to(root)}: checkpoint 2 must not create policies in "
        "data-platform."
    )

require(
    application,
    [
        "name: startup-apps-network-policy-aws-dev",
        "targetRevision: main",
        "path: clusters/aws-dev/security/network-policies/startup-apps",
        "namespace: startup-apps",
        "prune: true",
        "selfHeal: true",
    ],
    "Argo CD application contract",
)

require(
    runtime,
    [
        'APPLICATION_NAME="${APPLICATION_NAME:-startup-apps-network-policy-aws-dev}"',
        'EXPECTED_REVISION="${EXPECTED_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"',
        "describe-load-balancers",
        "kubernetes.io/role/elb",
        "Verifying ALB subnet CIDR alignment",
        "Verifying DNS and PostgreSQL egress",
        "Verifying unauthorized ingress is denied",
        "Verifying unauthorized egress is denied",
        "startup-apps NetworkPolicy aws-dev runtime validation passed.",
    ],
    "AWS runtime isolation matrix",
)

require(
    archive,
    [
        "Checkpoint 1 validated",
        "Checkpoint 2 validated",
        "ELB-tagged public subnet CIDRs",
        "TCP/5432",
        "data-platform default-deny is deferred",
    ],
    "checkpoint status and operating model",
)
PY

echo "startup-apps NetworkPolicy contract validation passed."
