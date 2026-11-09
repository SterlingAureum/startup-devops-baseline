#!/usr/bin/env python3
"""Validate rendered demo-api workload identity bindings."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


ENVIRONMENT_BINDINGS = (
    ("PLATFORM_RELEASE_ID", "platform.startup.dev/release-id"),
    ("PLATFORM_SOURCE_COMMIT", "platform.startup.dev/source-commit"),
    ("CONTAINER_IMAGE_DIGEST", "platform.startup.dev/image-digest"),
)

ANALYSIS_BINDINGS = (
    ("expected-release-id", "platform.startup.dev/release-id"),
    ("image-digest", "platform.startup.dev/image-digest"),
    ("source-commit", "platform.startup.dev/source-commit"),
)


def binding_count(manifest: str, name: str, annotation: str) -> int:
    """Count exact valueFrom.fieldRef bindings for one named list item."""

    pattern = re.compile(
        rf"^[ \t]*- name: {re.escape(name)}[ \t]*\n"
        rf"[ \t]+valueFrom:[ \t]*\n"
        rf"[ \t]+fieldRef:[ \t]*\n"
        rf"[ \t]+fieldPath: metadata\.annotations\['{re.escape(annotation)}'\][ \t]*$",
        re.MULTILINE,
    )
    return len(pattern.findall(manifest))


def validate_environment_projection(manifest: str, manifest_path: Path) -> None:
    for variable, annotation in ENVIRONMENT_BINDINGS:
        count = binding_count(manifest, variable, annotation)
        if count != 1:
            raise SystemExit(
                f"{variable} must have exactly one container Downward API binding "
                f"to {annotation} in {manifest_path}; observed {count}"
            )


def validate_rollout_analysis_projection(manifest: str, manifest_path: Path) -> None:
    expected_release_count = binding_count(
        manifest,
        "expected-release-id",
        "platform.startup.dev/release-id",
    )
    if expected_release_count < 1:
        raise SystemExit(
            f"Rollout AnalysisRun release identity binding is missing in {manifest_path}"
        )

    for argument, annotation in ANALYSIS_BINDINGS:
        count = binding_count(manifest, argument, annotation)
        if count != expected_release_count:
            raise SystemExit(
                f"AnalysisRun argument {argument} must bind {annotation} once per "
                f"analysis step in {manifest_path}; expected {expected_release_count}, "
                f"observed {count}"
            )


def validate_no_analysis_projection(manifest: str, manifest_path: Path) -> None:
    for argument, annotation in ANALYSIS_BINDINGS:
        count = binding_count(manifest, argument, annotation)
        if count != 0:
            raise SystemExit(
                f"Deployment unexpectedly renders AnalysisRun argument {argument} "
                f"for {annotation} in {manifest_path}"
            )


def validate_manifest(manifest_path: Path, workload: str) -> None:
    manifest = manifest_path.read_text()
    validate_environment_projection(manifest, manifest_path)
    if workload == "rollout":
        validate_rollout_analysis_projection(manifest, manifest_path)
    else:
        validate_no_analysis_projection(manifest, manifest_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollout", required=True, type=Path)
    parser.add_argument("--deployment", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_manifest(args.rollout, "rollout")
    validate_manifest(args.deployment, "deployment")
    print("Rendered demo-api workload and AnalysisRun identity projections passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
