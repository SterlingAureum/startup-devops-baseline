#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
repository = "https://github.com/SterlingAureum/startup-devops-baseline.git"

expected = {
    "clusters/local/root-app.yaml": "HEAD",
    "clusters/local/platform/demo-api.yaml": "HEAD",
    "clusters/local/platform/monitoring.yaml": "HEAD",
    "clusters/local/platform/namespace-guardrails.yaml": "HEAD",
    "clusters/aws/overlays/dev/root-app.yaml": "main",
    "clusters/aws/overlays/test/root-app.yaml": "main",
    "clusters/aws/overlays/prod/root-app.yaml": "main",
    "clusters/aws/base/platform/application-admission-policies.yaml": "main",
    "clusters/aws/base/platform/data-platform-network-policy.yaml": "main",
    "clusters/aws/base/platform/demo-api.yaml": "main",
    "clusters/aws/base/platform/external-secrets-startup-apps.yaml": "main",
    "clusters/aws/base/platform/namespace-guardrails.yaml": "main",
    "clusters/aws/base/platform/postgresql-baseline.yaml": "main",
    "clusters/aws/base/platform/runtime-qualification-rbac.yaml": "main",
    "clusters/aws/base/platform/startup-apps-network-policy.yaml": "main",
}

found = {}
for path in sorted((root / "clusters").rglob("*.yaml")):
    text = path.read_text()
    if f"repoURL: {repository}" not in text:
        continue

    relative = path.relative_to(root).as_posix()
    revisions = re.findall(r"^\s*targetRevision:\s*([^\s#]+)", text, re.MULTILINE)
    if len(revisions) != 1:
        raise SystemExit(
            f"{relative}: expected exactly one targetRevision for the repository source"
        )
    found[relative] = revisions[0]

missing = sorted(set(expected) - set(found))
unexpected = sorted(set(found) - set(expected))
if missing:
    raise SystemExit("Missing active repository Applications: " + ", ".join(missing))
if unexpected:
    raise SystemExit("Unclassified active repository Applications: " + ", ".join(unexpected))

errors = [
    f"{path}: expected targetRevision {expected[path]!r}, found {revision!r}"
    for path, revision in sorted(found.items())
    if revision != expected[path]
]
if errors:
    raise SystemExit("\n".join(errors))

for base in (root / "clusters", root / "scripts"):
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if re.search(r"targetRevision:\s*(?:feature/|refs/heads/feature/)", text):
            raise SystemExit(
                f"{path.relative_to(root)}: active GitOps contract contains a feature revision"
            )

print(
    "Active GitOps revision validation passed: "
    f"{sum(path.startswith('clusters/local/') for path in found)} local Applications use HEAD; "
    f"{sum(path.startswith('clusters/aws/') for path in found)} AWS base/root Applications use main."
)
PY
