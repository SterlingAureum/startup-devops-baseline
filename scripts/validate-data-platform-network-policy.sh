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
    / "data-platform"
    / "policies.yaml"
)
application = (
    root
    / "clusters"
    / "aws-dev"
    / "platform"
    / "data-platform-network-policy.yaml"
)
runtime = root / "scripts" / "validate-data-platform-network-policy-aws.sh"
archive = root / "docs" / "archive" / "V0.8.2_NETWORK_POLICY_ENFORCEMENT.md"

required_files = [policy, application, runtime, archive]
missing = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
if missing:
    raise SystemExit(
        "data-platform NetworkPolicy files are missing: " + ", ".join(missing)
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
        "name: allow-dns-egress",
        "name: allow-demo-api-to-postgresql-baseline",
        "platform.startup.dev/tier: application",
        "app.kubernetes.io/name: demo-api",
        "cnpg.io/cluster: postgresql-baseline",
        "name: allow-cnpg-operator-to-instances",
        "app.kubernetes.io/name: cloudnative-pg",
        "name: allow-cnpg-instance-traffic",
        "name: allow-cnpg-to-postgresql-rw-service",
        "cnpg.io/podRole: instance",
        "name: allow-kubernetes-api-to-cnpg-status",
        "name: allow-cnpg-to-barman-plugin",
        "app.kubernetes.io/name: plugin-barman-cloud",
        "name: allow-cnpg-to-kubernetes-api",
        "cidr: 172.20.0.10/32",
        "cidr: 172.20.14.237/32",
        "cidr: 172.20.104.64/32",
        "cidr: 172.20.0.1/32",
        "cidr: 10.20.10.230/32",
        "cidr: 10.20.11.76/32",
        "name: allow-cnpg-public-https-egress",
        "cidr: 0.0.0.0/0",
        "- 10.0.0.0/8",
        "- 100.64.0.0/10",
        "- 169.254.0.0/16",
        "- 172.16.0.0/12",
        "- 192.168.0.0/16",
        "port: 53",
        "port: 443",
        "port: 5432",
        "port: 8000",
        "port: 9090",
    ],
    "data-platform isolation policy contract",
)

policy_content = policy.read_text()
if policy_content.count("kind: NetworkPolicy") != 10:
    raise SystemExit(
        f"{policy.relative_to(root)}: expected exactly ten NetworkPolicy objects."
    )
if "cidr: 10.20.0.0/16" in policy_content:
    raise SystemExit(
        f"{policy.relative_to(root)}: internal HTTPS must not allow the whole VPC."
    )
if "namespace: startup-apps" in policy_content:
    raise SystemExit(
        f"{policy.relative_to(root)}: checkpoint 3 must not create policies in "
        "startup-apps."
    )

require(
    application,
    [
        "name: data-platform-network-policy-aws-dev",
        "targetRevision: feature/v0.8-production-security-baseline",
        "path: clusters/aws-dev/security/network-policies/data-platform",
        "namespace: data-platform",
        "prune: true",
        "selfHeal: true",
    ],
    "Argo CD application contract",
)

require(
    runtime,
    [
        'APPLICATION_NAME="${APPLICATION_NAME:-data-platform-network-policy-aws-dev}"',
        'EXPECTED_REVISION="${EXPECTED_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"',
        "Verifying private Kubernetes API endpoint alignment",
        "Verifying Service ClusterIP policy alignment",
        "Verifying CloudNativePG control and replication paths",
        "temporary-allow-cnpg-rw-service",
        'REPLICATION_TIMEOUT_SECONDS="${REPLICATION_TIMEOUT_SECONDS:-300}"',
        "Timed out waiting for every PostgreSQL replica to stream.",
        "Verifying Barman, Kubernetes API, S3, and STS egress",
        "Verifying fresh WAL archival after isolation",
        "Verifying unauthorized PostgreSQL ingress is denied",
        "Verifying unauthorized data-platform egress is denied",
        "data-platform NetworkPolicy aws-dev runtime validation passed.",
    ],
    "AWS runtime data-platform matrix",
)

require(
    archive,
    [
        "Checkpoint 2 validated",
        "Checkpoint 3 implemented",
        "private Kubernetes API endpoint",
        "RFC1918",
        "fresh WAL",
        "recovery and PITR",
    ],
    "checkpoint status and operating model",
)
PY

echo "data-platform NetworkPolicy contract validation passed."
