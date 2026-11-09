#!/usr/bin/env python3
"""Validate fail-closed CI change-impact routing without running workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class RoutingError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RoutingError(message)


def block(text: str, marker: str, next_prefix: str) -> str:
    start = text.find(marker)
    require(start >= 0, f"missing marker: {marker.strip()}")
    end = text.find(next_prefix, start + len(marker))
    return text[start:] if end < 0 else text[start:end]


def validate_repository(root: Path) -> dict[str, object]:
    workflows = root / ".github/workflows"
    validate_text = (workflows / "validate.yaml").read_text()
    reusable_text = (workflows / "reusable-quality-gates.yaml").read_text()
    image_text = (workflows / "demo-api-image-publish.yaml").read_text()
    root_gate = (root / "scripts/validate-ci-quality-gates.sh").read_text()

    validate_trigger = validate_text.split("permissions:", 1)[0]
    require("  pull_request:\n" in validate_trigger, "pull_request trigger removed")
    require("  push:\n    branches:\n      - main\n" in validate_trigger, "main push trigger removed")
    require("  workflow_dispatch:\n" in validate_trigger, "manual trigger removed")
    require("paths:" not in validate_trigger, "required workflow must remain always present")

    require(
        "  quality-gates:\n"
        "    uses: ./.github/workflows/reusable-quality-gates.yaml\n"
        "    with:\n"
        "      gate_mode: auto\n" in validate_text,
        "validate caller is not auto-routed",
    )
    require(
        "  quality-gates:\n"
        "    uses: ./.github/workflows/reusable-quality-gates.yaml\n"
        "    with:\n"
        "      gate_mode: image\n" in image_text,
        "image caller does not use image scope",
    )
    image_mode_callers = [
        path.name
        for path in workflows.glob("*.yaml")
        if "gate_mode: image" in path.read_text()
    ]
    require(
        image_mode_callers == ["demo-api-image-publish.yaml"],
        f"unreviewed image-mode caller: {image_mode_callers}",
    )
    require(
        "  build-and-push:\n"
        "    needs:\n"
        "      - quality-gates\n" in image_text,
        "image publication no longer depends on quality gates",
    )

    require("default: full" in reusable_text, "unknown reusable callers must default to full")
    required_fragments = (
        "id: impact",
        "classify-ci-change-impact.py",
        "if: steps.impact.outputs.mode == 'full'",
        "run: ./scripts/validate-ci-quality-gates.sh",
        "if: steps.impact.outputs.mode == 'documentation'",
        "run: ./scripts/validate-ci-documentation-change.sh",
        "if: steps.impact.outputs.mode == 'image'",
        "run: ./scripts/validate-demo-api-image-quality-gates.sh",
    )
    for fragment in required_fragments:
        require(fragment in reusable_text, f"routing fragment missing: {fragment}")
    gitleaks = block(
        reusable_text,
        "      - name: Scan repository for committed secrets\n",
        "\n      - name: ",
    )
    require("if:" not in gitleaks, "secret scanning must run in every mode")
    require(
        reusable_text.count("run: ./scripts/validate-ci-quality-gates.sh") == 1,
        "full gate invocation count changed",
    )
    routing_entrypoints = (
        '"${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh"',
        '"${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh"',
        '"${ROOT_DIR}/scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh"',
        '"${ROOT_DIR}/scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh"',
    )
    require(
        any(entrypoint in root_gate for entrypoint in routing_entrypoints),
        "root routing validator or reviewed successor missing",
    )
    require(
        '"${ROOT_DIR}/scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh"'
        not in root_gate.split(": <<'V012242_PRE_CORE_LEGACY_REGISTRATION'", 1)[0],
        "root still directly executes predecessor",
    )

    return {
        "status": "ci-change-impact-routing-validated",
        "required_check_job_id": "quality-gates",
        "default_mode": "full",
        "automatic_modes": ["documentation", "full"],
        "explicit_image_mode": True,
        "documentation_secret_scan_preserved": True,
        "workflow_triggers_preserved": True,
        "core_pull_request_main_push_deduplicated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(validate_repository(args.root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
