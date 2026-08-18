#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
workflow_dir = root / ".github" / "workflows"
publish_path = workflow_dir / "demo-api-image-publish.yaml"
quality_path = workflow_dir / "reusable-quality-gates.yaml"
dockerfile_path = root / "apps" / "demo-api" / "Dockerfile"
local_scan_path = root / "scripts" / "scan-demo-api-image.sh"

expected_actions = {
    "actions/attest": "f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6",
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/download-artifact": "37930b1c2abaa49bbe596cd826c3c89aef350131",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "aws-actions/configure-aws-credentials": (
        "e6de054238d6b7531b4e"
        "fff3b6587d9aade6a06c"
    ),
    "aquasecurity/trivy-action": "ed142fd0673e97e23eac54620cfb913e5ce36c25",
    "azure/setup-helm": "9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310",
    "docker/build-push-action": "53b7df96c91f9c12dcc8a07bcb9ccacbed38856a",
    "docker/login-action": "371161bbe7024a29a25c5e19bfcbc0804fe9ad2c",
    "docker/metadata-action": "dc802804100637a589fabce1cb79ff13a1411302",
    "docker/setup-buildx-action": "bb05f3f5519dd87d3ba754cc423b652a5edd6d2c",
    "gitleaks/gitleaks-action": "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e",
    "hashicorp/setup-terraform": "dfe3c3f87815947d99a8997f908cb6525fc44e9e",
}

uses_pattern = re.compile(
    r"^\s*uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s*(.+))?$"
)
seen_actions = set()

for workflow_path in sorted(workflow_dir.glob("*.yaml")):
    for line_number, line in enumerate(
        workflow_path.read_text().splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped.startswith("uses:"):
            continue
        if stripped.startswith("uses: ./"):
            continue

        match = uses_pattern.match(line)
        if not match:
            raise SystemExit(
                f"{workflow_path.relative_to(root)}:{line_number}: "
                "external Action reference is malformed"
            )

        action, revision, version_comment = match.groups()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise SystemExit(
                f"{workflow_path.relative_to(root)}:{line_number}: "
                f"{action} must be pinned to a full commit SHA"
            )
        if action not in expected_actions:
            raise SystemExit(
                f"{workflow_path.relative_to(root)}:{line_number}: "
                f"unreviewed external Action: {action}"
            )
        if revision != expected_actions[action]:
            raise SystemExit(
                f"{workflow_path.relative_to(root)}:{line_number}: "
                f"unexpected revision for {action}"
            )
        if not version_comment:
            raise SystemExit(
                f"{workflow_path.relative_to(root)}:{line_number}: "
                f"{action} pin must retain a readable version comment"
            )
        seen_actions.add(action)

missing_actions = sorted(set(expected_actions) - seen_actions)
if missing_actions:
    raise SystemExit(
        "Expected pinned Actions are missing: " + ", ".join(missing_actions)
    )


def require(block: str, values: list[str], description: str) -> None:
    for value in values:
        if value not in block:
            raise SystemExit(f"{description} is missing: {value}")


def step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = workflow.find(marker)
    if start < 0:
        raise SystemExit(f"Workflow step is missing: {name}")
    next_step = workflow.find("\n      - name: ", start + len(marker))
    if next_step < 0:
        return workflow[start:]
    return workflow[start:next_step]


quality = quality_path.read_text()
gitleaks = step_block(quality, "Scan repository for committed secrets")
require(
    gitleaks,
    [
        "GITLEAKS_ENABLE_COMMENTS: false",
        "GITLEAKS_ENABLE_UPLOAD_ARTIFACT: false",
    ],
    "Gitleaks gate",
)
config_scan = step_block(quality, "Scan demo-api configuration")
require(
    config_scan,
    [
        "scan-type: config",
        "scan-ref: apps/demo-api",
        "scanners: misconfig",
        "severity: HIGH,CRITICAL",
        "exit-code: 1",
        "version: v0.74.0",
    ],
    "Trivy configuration gate",
)

publish = publish_path.read_text()
push_trigger = publish.split("permissions:", 1)[0]
if re.search(r"(?m)^\s+tags:\s*$", push_trigger):
    raise SystemExit("Version tags must not rebuild the demo-api image")
if "type=ref,event=tag" in publish:
    raise SystemExit("Image metadata must not create a tag-event image alias")
ordered_steps = [
    "Build security candidate",
    "Scan image for fixable high and critical vulnerabilities",
    "Generate SPDX JSON SBOM",
    "Log in to GHCR",
    "Publish scanned image",
    "Attest image build provenance",
    "Attest image SBOM",
]
positions = [publish.find(f"      - name: {name}\n") for name in ordered_steps]
if any(position < 0 for position in positions):
    missing = [
        name for name, position in zip(ordered_steps, positions) if position < 0
    ]
    raise SystemExit("Publish workflow steps are missing: " + ", ".join(missing))
if positions != sorted(positions):
    raise SystemExit(
        "Build, scan, SBOM, registry login, push, and attestation steps "
        "are not ordered safely"
    )

build = step_block(publish, "Build security candidate")
require(
    build,
    ["load: true", "push: false", "pull: true"],
    "Pre-publication image build",
)

image_scan = step_block(
    publish, "Scan image for fixable high and critical vulnerabilities"
)
require(
    image_scan,
    [
        "scan-type: image",
        "scanners: vuln",
        "severity: HIGH,CRITICAL",
        "ignore-unfixed: true",
        "exit-code: 1",
        "version: v0.74.0",
    ],
    "Trivy image gate",
)

sbom = step_block(publish, "Generate SPDX JSON SBOM")
require(
    sbom,
    [
        "format: spdx-json",
        "output: ${{ runner.temp }}/demo-api.spdx.json",
    ],
    "SBOM generation",
)

publish_step = step_block(publish, "Publish scanned image")
require(
    publish_step,
    [
        'docker push "${image_reference}"',
        'echo "digest=${image_digest}" >> "${GITHUB_OUTPUT}"',
    ],
    "Scanned image publication",
)

provenance = step_block(publish, "Attest image build provenance")
require(
    provenance,
    [
        "subject-digest: ${{ steps.publish.outputs.digest }}",
        "push-to-registry: true",
    ],
    "Build provenance attestation",
)

sbom_attestation = step_block(publish, "Attest image SBOM")
require(
    sbom_attestation,
    [
        "subject-digest: ${{ steps.publish.outputs.digest }}",
        "sbom-path: ${{ runner.temp }}/demo-api.spdx.json",
        "push-to-registry: true",
    ],
    "SBOM attestation",
)

if not re.search(
    r"(?ms)^  promote-aws-dev:.*?^    needs:\n"
    r"      - build-and-push\n",
    publish,
):
    raise SystemExit(
        "Promotion PR job must depend on the complete scanned image job"
    )

dockerfile = dockerfile_path.read_text()
require(
    dockerfile,
    [
        "apt-get update",
        "apt-get upgrade --yes",
        "rm -rf /var/lib/apt/lists/*",
    ],
    "Debian security refresh",
)

local_scan = local_scan_path.read_text()
require(
    local_scan,
    [
        "EXPECTED_TRIVY_VERSION:-0.74.0",
        "--pkg-types os,library",
        "--severity HIGH,CRITICAL",
        "--ignore-unfixed",
        "--exit-code 1",
        ".release.imageDigest",
    ],
    "Immutable local image scan",
)
if "--vuln-type" in local_scan:
    raise SystemExit("Local image scan uses deprecated --vuln-type")
PY

echo "demo-api security supply-chain validation passed."
