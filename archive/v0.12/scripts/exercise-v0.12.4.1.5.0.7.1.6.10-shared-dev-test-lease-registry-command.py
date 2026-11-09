#!/usr/bin/env python3
"""Exercise the durable lease-owned registry composition through fixed fake."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import aws_two_wave_teardown_lease_registry_composition as COMPOSITION
import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_registry_runner as RUNNER
from aws_two_wave_teardown_core import TeardownGateError, require
from aws_two_wave_teardown_execution_lease import ExecutionLeaseStopped, PrivateExecutionLeaseStore
from aws_two_wave_teardown_private_preflight import SystemUtcClock
from aws_two_wave_teardown_receipt_approval import (
    PrivateReceiptApprovalStore,
    ReceiptApprovalStopped,
    StrictSinglePrivateFile,
)


CONFIRMATION = "consume-one-reviewed-approval-through-lease-owned-registry-fixed-fake"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--approval-store-directory", required=True, type=Path)
    value.add_argument("--execution-store-directory", required=True, type=Path)
    value.add_argument("--execution-request-file", required=True, type=Path)
    value.add_argument("--private-bindings-file", required=True, type=Path)
    value.add_argument("--expected-execution-request-sha256", required=True)
    value.add_argument("--expected-private-bindings-sha256", required=True)
    value.add_argument("--expected-receipt-sha256", required=True)
    value.add_argument("--expected-approval-record-sha256", required=True)
    value.add_argument("--confirm", required=True)
    return value


def run(argv: list[str], *, now_utc: str | None = None) -> dict:
    try:
        args = parser().parse_args(argv)
        require(args.confirm == CONFIRMATION, "Lease-registry command confirmation changed")
        for digest in (
            args.expected_execution_request_sha256,
            args.expected_private_bindings_sha256,
            args.expected_receipt_sha256,
            args.expected_approval_record_sha256,
        ):
            require(isinstance(digest, str) and REQUEST.SHA256.fullmatch(digest) is not None, "Expected digest changed")
        require(args.execution_request_file.is_absolute(), "Execution request path must be absolute")
        require(args.private_bindings_file.is_absolute(), "Private bindings path must be absolute")
        require(args.execution_request_file != args.private_bindings_file, "Private input files must be distinct")
        require(args.execution_request_file.parent != args.private_bindings_file.parent, "Private input directories must be distinct")
        clock = SystemUtcClock().now() if now_utc is None else now_utc
        execution_request = StrictSinglePrivateFile.read(args.execution_request_file)
        private_bindings = StrictSinglePrivateFile.read(args.private_bindings_file)
        require(
            REQUEST.sha256(private_bindings) == args.expected_private_bindings_sha256,
            "Private binding digest changed",
        )
        return COMPOSITION.run_lease_owned_registry_once(
            approval_store=PrivateReceiptApprovalStore(args.approval_store_directory),
            execution_store=PrivateExecutionLeaseStore(args.execution_store_directory),
            execution_request=execution_request,
            expected_execution_request_sha256=args.expected_execution_request_sha256,
            expected_receipt_sha256=args.expected_receipt_sha256,
            expected_approval_record_sha256=args.expected_approval_record_sha256,
            private_bindings=private_bindings,
            now_utc=clock,
            completed_at_utc=clock,
            backend=RUNNER.FixedFakeRegistryBackend(),
        )
    except COMPOSITION.LeaseRegistryCompositionStopped:
        raise
    except (ExecutionLeaseStopped, ReceiptApprovalStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise COMPOSITION.LeaseRegistryCompositionStopped("lease-registry-command-inputs-stopped") from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.buffer.write(REQUEST.canonical_bytes(result))
        return 0
    except (COMPOSITION.LeaseRegistryCompositionStopped, SystemExit):
        sys.stderr.write(
            "STOP: lease-owned fixed-fake registry command failed; preserve private stores and do not retry automatically.\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
