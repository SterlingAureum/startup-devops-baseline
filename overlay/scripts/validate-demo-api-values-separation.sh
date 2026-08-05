#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import json
import re
import sys

root = Path(sys.argv[1])
chart = root / "apps/demo-api/helm"
environments = ("aws-dev", "aws-test", "aws-prod")


def scalar_map(path):
    values = {}
    top_level = set()
    section = None
    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            top_level.add(section)
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            top_level.add(key)
            values[(None, key)] = value.strip()
            section = None
            continue
        if indent == 2 and section and ":" in stripped:
            key, value = stripped.split(":", 1)
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = json.loads(value)
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
            values[(section, key)] = value
    return top_level, values


for environment in environments:
    environment_file = chart / "values/environments" / f"{environment}.yaml"
    release_file = chart / "values/releases" / f"{environment}.yaml"
    if not environment_file.is_file() or not release_file.is_file():
        raise SystemExit(f"Missing values pair for {environment}")

    environment_top, environment_values = scalar_map(environment_file)
    required_environment_top = {
        "replicaCount", "image", "rollout", "analysis", "service",
        "ingress", "resources", "env", "database",
    }
    if not required_environment_top.issubset(environment_top):
        missing = sorted(required_environment_top - environment_top)
        raise SystemExit(f"{environment_file}: missing sections: {missing}")
    if environment_top & {"release", "delivery"}:
        raise SystemExit(f"{environment_file}: contains release identity")
    if environment_values.get(("image", "pullPolicy")) != "IfNotPresent":
        raise SystemExit(f"{environment_file}: image.pullPolicy is invalid")
    if any(
        key in environment_values
        for key in (
            ("image", "repository"),
            ("image", "tag"),
            ("image", "digest"),
            ("env", "APP_VERSION"),
        )
    ):
        raise SystemExit(f"{environment_file}: artifact identity leaked into environment values")
    if environment_values.get(("env", "APP_ENV")) != environment:
        raise SystemExit(f"{environment_file}: env.APP_ENV does not match its path")
    expected_host = {
        "aws-dev": "demo.dev.aureumstack.com",
        "aws-test": "demo.test.aureumstack.com",
        "aws-prod": "demo.prod.aureumstack.com",
    }[environment]
    if f"host: {expected_host}" not in environment_file.read_text():
        raise SystemExit(f"{environment_file}: expected hostname is missing")

    release_top, release_values = scalar_map(release_file)
    if release_top != {"image", "release", "delivery"}:
        raise SystemExit(
            f"{release_file}: only image, release, and delivery are allowed"
        )
    expected_fields = {
        ("image", "repository"),
        ("image", "tag"),
        ("image", "digest"),
        ("release", "applicationVersion"),
        ("delivery", "sourceRepository"),
        ("delivery", "sourceCommit"),
        ("delivery", "workflowRunId"),
    }
    if set(release_values) != expected_fields:
        raise SystemExit(f"{release_file}: release schema is not exact")

    repository = release_values[("image", "repository")]
    tag = release_values[("image", "tag")]
    digest = release_values[("image", "digest")]
    application_version = release_values[("release", "applicationVersion")]
    source_repository = release_values[("delivery", "sourceRepository")]
    source_commit = release_values[("delivery", "sourceCommit")]
    workflow_run_id = release_values[("delivery", "workflowRunId")]
    if repository != "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api":
        raise SystemExit(f"{release_file}: unexpected image repository")
    if source_repository != "SterlingAureum/startup-devops-baseline":
        raise SystemExit(f"{release_file}: unexpected source repository")
    if not re.fullmatch(r"sha-[0-9a-f]{7}", tag):
        raise SystemExit(f"{release_file}: invalid image tag")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"{release_file}: invalid image digest")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SystemExit(f"{release_file}: invalid source commit")
    if tag != f"sha-{source_commit[:7]}" or application_version != tag:
        raise SystemExit(f"{release_file}: readable identities are inconsistent")
    if not workflow_run_id:
        raise SystemExit(f"{release_file}: workflowRunId is empty")

legacy_file = chart / "values-aws-dev.yaml"
if legacy_file.exists():
    raise SystemExit(f"Legacy mixed values file still exists: {legacy_file}")

application = (root / "clusters/aws-dev/platform/demo-api.yaml").read_text()
ordered_values = """      valueFiles:
        - values/environments/aws-dev.yaml
        - values/releases/aws-dev.yaml"""
if ordered_values not in application:
    raise SystemExit("aws-dev Application does not load environment then release values")

base_values = (chart / "values.yaml").read_text()
if "release:\n  applicationVersion:" not in base_values:
    raise SystemExit("Base values do not define release.applicationVersion")
if "  APP_VERSION:" in base_values:
    raise SystemExit("Base env still owns APP_VERSION")

helpers = (chart / "templates/_helpers.tpl").read_text()
for marker in (
    ".Values.release.applicationVersion",
    'required "release.applicationVersion is required"',
):
    if marker not in helpers:
        raise SystemExit(f"Chart release identity contract is missing: {marker}")

publish = (root / ".github/workflows/demo-api-image-publish.yaml").read_text()
rollback = (root / ".github/workflows/demo-api-rollback.yaml").read_text()
release_path = "apps/demo-api/helm/values/releases/aws-dev.yaml"
environment_path = "apps/demo-api/helm/values/environments/aws-dev.yaml"
for name, workflow in (("publish", publish), ("rollback", rollback)):
    if release_path not in workflow or environment_path not in workflow:
        raise SystemExit(f"{name} workflow does not render the split aws-dev values")

print("demo-api environment/release values separation passed.")
PY
