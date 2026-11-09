#!/usr/bin/env python3
"""Local-only receipt persistence and phase-approval CLI; no live executor."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError, require
from aws_two_wave_teardown_private_preflight import SystemUtcClock
from aws_two_wave_teardown_receipt_approval import (
    PrivateReceiptApprovalStore,
    ReceiptApprovalStopped,
    StrictSinglePrivateFile,
)


PERSIST_CONFIRMATION = "persist-reviewed-shared-two-wave-preflight-receipt"
APPROVAL_CONFIRMATION = "record-reviewed-shared-two-wave-phase-approval"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    subparsers = value.add_subparsers(dest="command", required=True)
    persist = subparsers.add_parser("persist-receipt")
    persist.add_argument("--store-directory", required=True, type=Path)
    persist.add_argument("--preflight-result-file", required=True, type=Path)
    persist.add_argument("--expected-preflight-result-sha256", required=True)
    persist.add_argument("--confirm", required=True)
    approve = subparsers.add_parser("record-approval")
    approve.add_argument("--store-directory", required=True, type=Path)
    approve.add_argument("--approval-request-file", required=True, type=Path)
    approve.add_argument("--expected-approval-request-sha256", required=True)
    approve.add_argument("--expected-receipt-sha256", required=True)
    approve.add_argument("--confirm", required=True)
    return value


def run(argv: list[str], *, now_utc: str | None = None) -> dict:
    try:
        args = parser().parse_args(argv)
        clock = SystemUtcClock().now() if now_utc is None else now_utc
        store = PrivateReceiptApprovalStore(args.store_directory)
        if args.command == "persist-receipt":
            require(args.confirm == PERSIST_CONFIRMATION, "Receipt persistence confirmation changed")
            require(REQUEST.SHA256.fullmatch(args.expected_preflight_result_sha256) is not None, "Expected preflight-result digest changed")
            value = StrictSinglePrivateFile.read(args.preflight_result_file)
            return store.persist_receipt(value, expected_result_sha256=args.expected_preflight_result_sha256, now_utc=clock)
        require(args.command == "record-approval" and args.confirm == APPROVAL_CONFIRMATION, "Phase approval confirmation changed")
        require(REQUEST.SHA256.fullmatch(args.expected_approval_request_sha256) is not None, "Expected approval-request digest changed")
        require(REQUEST.SHA256.fullmatch(args.expected_receipt_sha256) is not None, "Expected receipt digest changed")
        value = StrictSinglePrivateFile.read(args.approval_request_file)
        return store.record_approval(value, expected_approval_request_sha256=args.expected_approval_request_sha256, expected_receipt_sha256=args.expected_receipt_sha256, now_utc=clock)
    except ReceiptApprovalStopped:
        raise
    except (OSError, TypeError, ValueError, KeyError, TeardownGateError):
        raise ReceiptApprovalStopped("receipt-approval-inputs-stopped") from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.buffer.write(REQUEST.canonical_bytes(result))
        return 0
    except (ReceiptApprovalStopped, SystemExit):
        sys.stderr.write("STOP: shared two-wave receipt/approval operation failed; preserve the private store and do not retry automatically.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
