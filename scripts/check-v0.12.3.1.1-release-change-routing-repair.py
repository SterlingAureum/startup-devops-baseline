#!/usr/bin/env python3
"""Validate the fail-closed release-change route without running GitHub Actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class RoutingRepairError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RoutingRepairError(message)


def step_block(text: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    start = text.find(marker)
    require(start >= 0, f"missing workflow step: {name}")
    end = text.find("\n      - name: ", start + len(marker))
    return text[start:] if end < 0 else text[start:end]


def validate_repository(root: Path) -> dict[str, object]:
    reusable = (root / ".github/workflows/reusable-quality-gates.yaml").read_text()
    classifier = (root / "scripts/classify-ci-change-impact.py").read_text()
    tests = (root / "scripts/test-ci-change-impact.py").read_text()
    release_gate = (root / "scripts/validate-demo-api-release-quality-gates.sh").read_text()
    root_gate = (root / "scripts/validate-ci-quality-gates.sh").read_text()
    validator_topology = (
        root / "scripts/check-v0.12.2.4.1-validator-orchestration.py"
    ).read_text()
    topology = (root / "scripts/check-v0.12.2.4.2-quality-gate-orchestration.py").read_text()

    require(
        'r"apps/demo-api/helm/values/releases/aws-(dev|test|prod)\\.yaml"'
        in classifier,
        "exact release path expression missing",
    )
    require(
        "release_only = len(paths) == 1 and is_release_path(paths[0])" in classifier,
        "single-path release boundary missing",
    )
    require(
        'else "release"\n            if release_only' in classifier,
        "automatic release classification missing",
    )
    require(
        'if requested_mode == "release"' not in classifier,
        "explicit release bypass exposed",
    )
    for marker in (
        "test_exact_release_change_is_targeted_for_pull_request_and_push",
        "test_release_change_mixed_with_any_other_path_is_full",
        "test_release_adjacent_paths_are_full",
        "test_explicit_release_request_is_not_exposed",
    ):
        require(marker in tests, f"release classifier coverage missing: {marker}")

    release_step = step_block(reusable, "Run demo-api release quality gates")
    require(
        "if: steps.impact.outputs.mode == 'release'" in release_step,
        "release workflow condition drift",
    )
    require(
        "run: ./scripts/validate-demo-api-release-quality-gates.sh" in release_step,
        "release workflow entrypoint drift",
    )
    secret_step = step_block(reusable, "Scan repository for committed secrets")
    require("if:" not in secret_step, "release mode lost unconditional secret scan")
    trivy_step = step_block(reusable, "Scan demo-api configuration")
    require(
        "if: steps.impact.outputs.mode != 'documentation'" in trivy_step,
        "release mode lost Trivy config scan",
    )
    setup_step = step_block(reusable, "Setup Helm")
    require(
        "if: steps.impact.outputs.mode != 'documentation'" in setup_step,
        "release mode lost Helm setup",
    )

    for command in (
        "validate-demo-api-values-separation.sh",
        "validate-demo-api-promotion.sh",
        "validate-demo-api-promotion-governance.sh",
        "helm lint",
        "helm template",
        "git -C \"${ROOT_DIR}\" diff --check",
    ):
        require(command in release_gate, f"release gate missing: {command}")
    require(
        "validate-ci-quality-gates.sh" not in release_gate
        and "quality-gate-history" not in release_gate,
        "release gate replays historical repository validators",
    )
    require(
        '"${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh"'
        in root_gate,
        "root gate does not use the repair successor",
    )
    require(
        '"${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh"'
        not in root_gate.split(": <<'V012242_PRE_CORE_LEGACY_REGISTRATION'", 1)[0],
        "root gate still directly invokes the predecessor",
    )
    require(
        '"validate-v0.12.3.1.1-release-change-routing-repair.sh": LATEST_ORCHESTRATOR'
        in topology,
        "historical topology checker is not successor-aware",
    )
    require(
        '"validate-v0.12.3.1.1-release-change-routing-repair.sh": LATEST'
        in validator_topology,
        "historical validator topology checker is not successor-aware",
    )

    return {
        "status": "release-change-routing-repair-validated",
        "automaticModes": ["documentation", "release", "full"],
        "releaseChangedPathCount": 1,
        "releasePullRequestSupported": True,
        "releaseMainPushSupported": True,
        "mixedChangesFailClosed": True,
        "explicitReleaseModeExposed": False,
        "historicalReplayInReleaseMode": False,
        "secretScanPreserved": True,
        "trivyConfigScanPreserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(validate_repository(args.root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
