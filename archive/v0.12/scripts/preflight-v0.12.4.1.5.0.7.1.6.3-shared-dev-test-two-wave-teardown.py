#!/usr/bin/env python3
"""Local-only private bundle preflight; exposes no infrastructure executor."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError, require
from aws_two_wave_teardown_private_preflight import (
    PrivatePreflightStopped,
    StrictPrivateBundleReader,
    SystemUtcClock,
    verify_private_bundle,
)


CONFIRMATION = "observe-reviewed-shared-two-wave-private-preflight"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=("verify",))
    value.add_argument("--bundle-directory", required=True, type=Path)
    value.add_argument("--expected-control-plane-commit", required=True)
    value.add_argument("--environment", required=True, choices=("aws-dev", "aws-test"))
    value.add_argument("--phase", required=True, choices=tuple(REQUEST.PHASES))
    value.add_argument("--expected-request-sha256", required=True)
    value.add_argument("--expected-evidence-sha256", required=True)
    value.add_argument("--confirm", required=True)
    return value


def run(argv: list[str], *, now_utc: str | None = None) -> dict:
    try:
        args = parser().parse_args(argv)
        require(args.command == "verify" and args.confirm == CONFIRMATION, "Private preflight confirmation changed")
        require(REQUEST.COMMIT.fullmatch(args.expected_control_plane_commit) is not None, "Expected control-plane commit changed")
        require(REQUEST.SHA256.fullmatch(args.expected_request_sha256) is not None, "Expected request digest changed")
        require(REQUEST.SHA256.fullmatch(args.expected_evidence_sha256) is not None, "Expected evidence digest changed")
        inputs = StrictPrivateBundleReader(args.bundle_directory).read()
        clock = SystemUtcClock().now() if now_utc is None else now_utc
        result = verify_private_bundle(
            inputs["request"],
            inputs["evidence"],
            expected_request_sha256=args.expected_request_sha256,
            expected_evidence_sha256=args.expected_evidence_sha256,
            now_utc=clock,
        )
        receipt = result["receipt"]
        require(receipt["controlPlaneCommit"] == args.expected_control_plane_commit, "CLI commit binding changed")
        require(receipt["environment"] == args.environment, "CLI environment binding changed")
        require(receipt["phase"] == args.phase, "CLI phase binding changed")
        return result
    except PrivatePreflightStopped:
        raise
    except (OSError, TypeError, ValueError, KeyError, TeardownGateError):
        raise PrivatePreflightStopped("private-preflight-inputs-stopped") from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.buffer.write(REQUEST.canonical_bytes(result))
        return 0
    except (PrivatePreflightStopped, SystemExit):
        sys.stderr.write("STOP: shared two-wave private preflight failed; preserve private inputs and do not retry automatically.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
