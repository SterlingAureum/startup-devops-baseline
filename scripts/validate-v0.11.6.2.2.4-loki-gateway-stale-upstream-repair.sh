#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
import base64
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
contract = json.loads((root / "delivery/contracts/v0.11.6.2.2.4-loki-gateway-stale-upstream-repair.json").read_text())
assert contract["schemaVersion"] == contract["version"] == "v0.11.6.2.2.4"
assert contract["predecessor"] == "v0.11.6.2.2.3"
assert contract["incident"]["gatewayHttpStatus"] == 502
assert contract["incident"]["directLokiHttpStatus"] == 200
assert contract["incident"]["rootCause"] == "gateway-nginx-retained-replaced-loki-service-cluster-ip"
assert all(contract["repair"].values())
assert contract["acceptance"]["consecutiveLiveRunsRequired"] == 2
assert contract["acceptance"]["imageRebuildRequired"] is False
assert contract["acceptance"]["awsRuntimeChanged"] is False

restore = (root / "scripts/restore-local-gitops-baseline.sh").read_text()
for marker in (
    "loki_service_ip_before", "loki_service_ip_after",
    'sync_application_if_needed "${LOKI_APP_NAME}"',
    '"${loki_service_ip_before}" != "${loki_service_ip_after}"',
    'rollout restart', 'rollout status', 'deployment/${LOKI_GATEWAY_DEPLOYMENT}',
):
    assert marker in restore, marker

live = (root / "scripts/check-local-demo-api-trace-correlation.sh").read_text()
for marker in (
    "tempo_trace_matches", "normalize_identifier", "base64.b64decode",
    "decoded.hex()", "after identifier normalization",
):
    assert marker in live, marker
for forbidden in ('rollout restart', 'kubectl delete', 'kubectl patch'):
    assert forbidden not in live, forbidden

expected = "920216107ee6fe40"
encoded = base64.b64encode(bytes.fromhex(expected)).decode()
assert base64.b64decode(encoded, validate=True).hex() == expected

doc = (root / contract["designDocument"]).read_text()
for marker in (
    "Classic incident", "10.96.150.207", "198.18.0.195",
    "Immediate recovery", "Declarative prevention",
    "Service ClusterIP and Endpoint Pod IP normally differ",
    "protobuf-JSON query representation may return those byte fields as",
):
    assert marker in doc, marker

print("v0.11.6.2.2.4 stale Gateway upstream, bounded recovery, Tempo identifier normalization, and troubleshooting contracts passed.")
PY
