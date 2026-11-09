#!/usr/bin/env python3
"""Derive the deterministic demo-api Release ID from one release values file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG = re.compile(r"^sha-[0-9a-f]{7}$")


def read_release(path: Path) -> dict[tuple[str, str], str]:
    if not path.is_file():
        raise ValueError(f"Release values file does not exist: {path}")
    section: str | None = None
    values: dict[tuple[str, str], str] = {}
    for raw in path.read_text().splitlines():
        if raw and not raw.startswith(" ") and raw.rstrip().endswith(":"):
            section = raw.strip()[:-1]
            continue
        match = re.fullmatch(r"  ([A-Za-z][A-Za-z0-9]*):\s*(.+)", raw)
        if section is None or match is None:
            continue
        key, encoded = match.groups()
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError:
            value = encoded.strip()
        if isinstance(value, str):
            values[(section, key)] = value
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-file", required=True, type=Path)
    parser.add_argument("--format", choices=("id", "json"), default="id")
    args = parser.parse_args()

    values = read_release(args.release_file)
    source = values.get(("delivery", "sourceCommit"), "")
    digest = values.get(("image", "digest"), "")
    tag = values.get(("image", "tag"), "")
    application_version = values.get(("release", "applicationVersion"), "")

    if SHA.fullmatch(source) is None:
        raise SystemExit("delivery.sourceCommit is not a full lowercase Git SHA")
    if DIGEST.fullmatch(digest) is None:
        raise SystemExit("image.digest is not a full lowercase sha256 digest")
    expected_tag = f"sha-{source[:7]}"
    if TAG.fullmatch(tag) is None or tag != expected_tag:
        raise SystemExit("image.tag does not match delivery.sourceCommit")
    if application_version != tag:
        raise SystemExit("release.applicationVersion does not match image.tag")

    release_id = f"demo-api-{source[:12]}-{digest.removeprefix('sha256:')[:12]}"
    if args.format == "json":
        print(json.dumps({
            "releaseId": release_id,
            "sourceCommit": source,
            "imageDigest": digest,
            "imageTag": tag,
        }, indent=2))
    else:
        print(release_id)


if __name__ == "__main__":
    main()
