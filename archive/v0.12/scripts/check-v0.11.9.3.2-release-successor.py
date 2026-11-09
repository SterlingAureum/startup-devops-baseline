#!/usr/bin/env python3
"""Accept the historical aws-dev release or its one reviewed successor."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-file", required=True, type=Path)
    parser.add_argument("--readiness-contract", required=True, type=Path)
    parser.add_argument("--successor-contract", required=True, type=Path)
    args = parser.parse_args()

    readiness = json.loads(args.readiness_contract.read_text())
    release_bytes = args.release_file.read_bytes()
    release_sha256 = hashlib.sha256(release_bytes).hexdigest()
    relative = "apps/demo-api/helm/values/releases/aws-dev.yaml"

    if release_sha256 == readiness["releaseFiles"][relative]:
        print("historical-baseline")
        return

    if not args.successor_contract.is_file():
        raise SystemExit("aws-dev release identity changed without the reviewed successor contract")

    successor = json.loads(args.successor_contract.read_text())
    if successor.get("predecessor") != "v0.11.9.3.2":
        raise SystemExit("aws-dev release identity changed under an unrelated successor contract")
    if successor["releaseFilePolicy"]["allowedAwsDevSuccessor"] != "selectedCandidate":
        raise SystemExit("successor does not select the reviewed candidate")

    candidate = successor["selectedCandidate"]
    expected = {
        "image": {
            "repository": candidate["repository"],
            "tag": candidate["tag"],
            "digest": candidate["digest"],
        },
        "release": {
            "applicationVersion": candidate["tag"],
        },
        "delivery": {
            "sourceRepository": candidate["sourceRepository"],
            "sourceCommit": candidate["sourceCommit"],
            "workflowRunId": candidate["workflowRunId"],
        },
    }
    actual = yaml.safe_load(release_bytes)
    if actual != expected:
        raise SystemExit("aws-dev release identity is neither the historical baseline nor the reviewed selected candidate")

    print("reviewed-selected-candidate")


if __name__ == "__main__":
    main()
