#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re


CAPABILITIES = (
    "metrics", "dashboards", "alerts", "logs", "traces", "slo",
    "progressiveDeliveryTelemetry",
)
CAPABILITY_STATUSES = {
    "supported-verified", "supported-not-verified", "not-deployed",
    "not-applicable",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fail(message: str) -> None:
    raise SystemExit(message)


def reject_sensitive_values(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"(?i)(secret|token|password|credential|kubeconfig|private.?key|signed.?url)", key):
                fail("runtime facts contain a sensitive key")
            reject_sensitive_values(item)
    elif isinstance(value, list):
        for item in value:
            reject_sensitive_values(item)
    elif isinstance(value, str):
        if re.search(r"(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|bearer\s+[A-Za-z0-9._~+/-]+=*|AKIA[0-9A-Z]{16}|X-Amz-Signature=)", value):
            fail("runtime facts contain sensitive material")


parser = argparse.ArgumentParser()
parser.add_argument("--status", required=True, choices=("qualified", "waiting-runtime", "failed"))
parser.add_argument("--reason", required=True)
parser.add_argument("--started-at", required=True)
parser.add_argument("--aws-account-id", required=True)
parser.add_argument("--aws-region", required=True)
parser.add_argument("--cluster-name", required=True)
parser.add_argument("--kube-context", required=True)
parser.add_argument("--repository-commit", required=True)
parser.add_argument("--target-revision", required=True)
parser.add_argument("--application-version", required=True)
parser.add_argument("--runtime-facts")
parser.add_argument("--output", required=True)
args = parser.parse_args()

if not re.fullmatch(r"[0-9]{12}", args.aws_account_id):
    fail("aws account ID must contain exactly 12 digits")
if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]+", args.aws_region):
    fail("invalid AWS region")
for name, value in (("repository commit", args.repository_commit), ("target revision", args.target_revision)):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        fail(f"{name} must be a full lowercase commit SHA")
if not args.cluster_name or not args.kube_context or not args.application_version:
    fail("cluster, context, and application version must be non-empty")

capabilities = {
    "metrics": {"status": "supported-not-verified", "evidenceCheckIds": []},
    "dashboards": {"status": "supported-not-verified", "evidenceCheckIds": []},
    "alerts": {"status": "supported-not-verified", "evidenceCheckIds": []},
    "logs": {"status": "not-deployed", "evidenceCheckIds": []},
    "traces": {"status": "not-deployed", "evidenceCheckIds": []},
    "slo": {"status": "supported-not-verified", "evidenceCheckIds": []},
    "progressiveDeliveryTelemetry": {"status": "not-applicable", "evidenceCheckIds": []},
}
checks = [{"id": "runtime.discovery", "outcome": "not-run", "observedValue": None, "diagnostic": args.reason}]

if args.runtime_facts:
    facts = json.loads(Path(args.runtime_facts).read_text())
    reject_sensitive_values(facts)
    if set(facts) != {"capabilities", "checks"}:
        fail("runtime facts must contain exactly capabilities and checks")
    if list(facts["capabilities"]) != list(CAPABILITIES):
        fail("runtime capability inventory is incomplete or out of order")
    check_ids = {item["id"] for item in facts["checks"]}
    if len(check_ids) != len(facts["checks"]):
        fail("runtime check IDs must be unique")
    for capability in facts["capabilities"].values():
        if capability.get("status") not in CAPABILITY_STATUSES:
            fail("invalid runtime capability status")
        if not set(capability.get("evidenceCheckIds", ())) <= check_ids:
            fail("capability references an unknown check")
    capabilities = facts["capabilities"]
    checks = facts["checks"]

if args.status == "qualified":
    if any(item["outcome"] != "passed" for item in checks):
        fail("qualified evidence requires every recorded mandatory check to pass")
    if not any(item["status"] == "supported-verified" for item in capabilities.values()):
        fail("qualified evidence requires at least one verified capability")
elif args.status == "waiting-runtime":
    if any(item["status"] == "supported-verified" for item in capabilities.values()):
        fail("waiting-runtime evidence cannot contain verified capabilities")

document = {
    "schemaVersion": "v0.11.8.0",
    "qualificationVersion": "v0.11.8.1",
    "environment": "aws-dev",
    "status": args.status,
    "observationWindow": {"startedAt": args.started_at, "finishedAt": utc_now()},
    "identity": {
        "awsAccountId": args.aws_account_id,
        "awsRegion": args.aws_region,
        "clusterName": args.cluster_name,
        "kubeContext": args.kube_context,
        "repositoryCommit": args.repository_commit,
        "targetRevision": args.target_revision,
        "applicationVersion": args.application_version,
    },
    "approval": {"required": False, "approved": False, "reference": None},
    "capabilities": capabilities,
    "checks": checks,
}

output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(document, indent=2) + "\n")
print(output)
