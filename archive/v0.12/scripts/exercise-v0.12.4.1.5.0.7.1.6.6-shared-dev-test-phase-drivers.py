#!/usr/bin/env python3
"""Exercise one reviewed phase-driver spec through the closed fixed fake."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError, require
from aws_two_wave_teardown_private_preflight import SystemUtcClock
from aws_two_wave_teardown_receipt_approval import (
    PrivateReceiptApprovalStore,
    ReceiptApprovalStopped,
    StrictSinglePrivateFile,
)


CONFIRMATION = "consume-one-approval-for-reviewed-fixed-fake-phase-driver"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--approval-store-directory", required=True, type=Path)
    value.add_argument("--execution-store-directory", required=True, type=Path)
    value.add_argument("--execution-request-file", required=True, type=Path)
    value.add_argument("--expected-execution-request-sha256", required=True)
    value.add_argument("--expected-receipt-sha256", required=True)
    value.add_argument("--expected-approval-record-sha256", required=True)
    value.add_argument("--confirm", required=True)
    return value


def run(argv: list[str], *, now_utc: str | None = None) -> dict:
    try:
        args = parser().parse_args(argv)
        require(args.confirm == CONFIRMATION, "Phase-driver exercise confirmation changed")
        for digest in (
            args.expected_execution_request_sha256,
            args.expected_receipt_sha256,
            args.expected_approval_record_sha256,
        ):
            require(REQUEST.SHA256.fullmatch(digest) is not None, "Expected digest changed")
        clock = SystemUtcClock().now() if now_utc is None else now_utc
        execution_request = StrictSinglePrivateFile.read(args.execution_request_file)
        return DRIVERS.run_reviewed_phase_spec_once(
            approval_store=PrivateReceiptApprovalStore(args.approval_store_directory),
            execution_store=LEASE.PrivateExecutionLeaseStore(args.execution_store_directory),
            execution_request=execution_request,
            expected_execution_request_sha256=args.expected_execution_request_sha256,
            expected_receipt_sha256=args.expected_receipt_sha256,
            expected_approval_record_sha256=args.expected_approval_record_sha256,
            now_utc=clock,
            completed_at_utc=clock,
            transport=DRIVERS.FixedFakePhaseTransport(),
        )
    except DRIVERS.PhaseDriverStopped:
        raise
    except (LEASE.ExecutionLeaseStopped, ReceiptApprovalStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise DRIVERS.PhaseDriverStopped("phase-driver-exercise-inputs-stopped") from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.buffer.write(REQUEST.canonical_bytes(result))
        return 0
    except (DRIVERS.PhaseDriverStopped, SystemExit):
        sys.stderr.write(
            "STOP: reviewed phase-driver exercise failed; preserve both private stores and do not retry automatically.\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
