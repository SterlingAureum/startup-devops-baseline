#!/usr/bin/env python3
"""Run one reviewed aws-dev residual-cost audit with redacted public output."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts/preflight-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"
AUDIT_PATH = ROOT / "scripts/validate-aws-cost-cleanup.sh"
EXECUTION_CONFIRMATION = "execute-reviewed-aws-dev-residual-cost-audit"
MAXIMUM_WINDOW_SECONDS = 14400
MINIMUM_REMAINING_SECONDS = 900

spec = importlib.util.spec_from_file_location("aws_dev_residual_cost_preflight", PREFLIGHT_PATH)
assert spec and spec.loader
PREFLIGHT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREFLIGHT)

Preflight = Callable[[str], dict[str, object]]
Audit = Callable[[], tuple[int, str, str]]


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Audit window timestamps must be UTC")
    return parsed.astimezone(timezone.utc)


def require_private_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Reviewed preflight result must be a regular file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Reviewed preflight result mode must be 600")
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError("Reviewed preflight directory must be private")
    return json.loads(path.read_text())


def require_private_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Private audit output directory must be a regular directory")
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ValueError("Private audit output directory mode must be 700")


def write_private(path: Path, content: str) -> bytes:
    data = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Private audit output mode must be 600")
    return data


def default_audit() -> tuple[int, str, str]:
    env = os.environ.copy()
    env["AWS_ENVIRONMENT"] = "aws-dev"
    env["AWS_PAGER"] = ""
    for key in (
        "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION",
        "CONFIRM_AWS_DEV_APPLY",
        "CONFIRM_AWS_TEST_APPLY",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [str(AUDIT_PATH)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def execute(
    mode: str,
    expected_commit: str,
    preflight_path: Path,
    expected_preflight_sha256: str,
    start_utc: str,
    end_utc: str,
    private_output_directory: Path | None,
    *,
    now: datetime | None = None,
    preflight: Preflight = PREFLIGHT.execute,
    audit: Audit = default_audit,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_preflight_sha256):
        raise ValueError("Expected preflight SHA must be a lowercase SHA-256")
    preflight_data = preflight_path.read_bytes()
    if hashlib.sha256(preflight_data).hexdigest() != expected_preflight_sha256:
        raise ValueError("Reviewed preflight result fingerprint changed")
    reviewed = require_private_json(preflight_path)
    if reviewed.get("control_plane_commit") != expected_commit:
        raise ValueError("Reviewed preflight commit does not match execution commit")
    if reviewed.get("status") != "aws-dev-residual-cost-audit-preflight-ready-for-separate-approval":
        raise ValueError("Reviewed preflight did not reach the ready state")
    for key in ("execution_authorized", "full_audit_executed", "mutation_executed", "aws_test_created"):
        if reviewed.get(key) is not False:
            raise ValueError(f"Reviewed preflight boundary changed: {key}")

    start = parse_utc(start_utc)
    end = parse_utc(end_utc)
    current = now or datetime.now(timezone.utc)
    duration = int((end - start).total_seconds())
    remaining = int((end - current).total_seconds())
    if duration <= 0 or duration > MAXIMUM_WINDOW_SECONDS:
        raise ValueError("Audit window must be positive and no longer than four hours")
    if current < start or current >= end or remaining < MINIMUM_REMAINING_SECONDS:
        raise ValueError("Current time is outside the reviewed audit execution window")

    immediate = preflight(expected_commit)
    if immediate != reviewed:
        raise ValueError("Immediate preflight does not match the reviewed result")

    common = {
        "control_plane_commit": expected_commit,
        "reviewed_preflight_sha256": expected_preflight_sha256,
        "remaining_window_seconds": remaining,
        "immediate_preflight_matched": True,
        "target_environment": "aws-dev",
        "aws_account_verified": True,
        "account_id_emitted": False,
        "automatic_retry_performed": False,
        "mutation_executed": False,
        "aws_test_created": False,
    }
    if mode == "verify":
        return {
            **common,
            "status": "aws-dev-residual-cost-audit-execution-inputs-verified",
            "execution_authorized": False,
            "full_audit_executed": False,
            "next_action": "obtain-separate-aws-dev-residual-cost-audit-approval",
        }
    if mode != "execute":
        raise ValueError("Mode must be verify or execute")
    if os.environ.get("CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION") != EXECUTION_CONFIRMATION:
        raise ValueError("Separate aws-dev residual-cost audit confirmation is required")
    if private_output_directory is None:
        raise ValueError("Execute mode requires a private output directory")
    require_private_directory(private_output_directory)

    stdout_path = private_output_directory / "residual-cost-audit.stdout"
    stderr_path = private_output_directory / "residual-cost-audit.stderr"
    audit_exit, audit_stdout, audit_stderr = audit()
    stdout_data = write_private(stdout_path, audit_stdout)
    stderr_data = write_private(stderr_path, audit_stderr)

    success_markers = (
        "AWS cleanup audit passed for aws-dev.",
        "No continuing cluster, network, compute, volume, load-balancer, bucket, certificate, DNS, or tagged-resource identity was found.",
    )
    audit_passed = audit_exit == 0 and all(
        marker in audit_stdout for marker in success_markers
    )
    fleet_matches = re.findall(
        r"Accepted ([0-9]+) terminal or expired EC2 Fleet record\(s\)",
        audit_stdout,
    )
    if len(fleet_matches) > 1:
        audit_passed = False
    terminal_fleet_count = int(fleet_matches[0]) if len(fleet_matches) == 1 else 0

    if audit_passed:
        status = "aws-dev-residual-cost-audit-complete"
        next_action = "record-aws-dev-residual-cost-audit-execution-evidence"
    else:
        status = "aws-dev-residual-cost-audit-failed"
        next_action = "inspect-private-audit-output-and-obtain-new-approval"

    return {
        **common,
        "status": status,
        "execution_authorized": True,
        "full_audit_executed": True,
        "audit_exit_code": audit_exit,
        "audit_passed": audit_passed,
        "continuing_cost_identity_found": False if audit_passed else None,
        "terminal_or_expired_fleet_record_count": terminal_fleet_count,
        "private_stdout_sha256": hashlib.sha256(stdout_data).hexdigest(),
        "private_stderr_sha256": hashlib.sha256(stderr_data).hexdigest(),
        "private_output_mode": "0600",
        "private_resource_id_output_committed": False,
        "next_action": next_action,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    parser.add_argument("--preflight-result", required=True, type=Path)
    parser.add_argument("--expected-preflight-sha256", required=True)
    parser.add_argument("--start-utc", required=True)
    parser.add_argument("--end-utc", required=True)
    parser.add_argument("--private-output-directory", type=Path)
    args = parser.parse_args()
    result = execute(
        args.mode,
        args.expected_control_plane_commit,
        args.preflight_result,
        args.expected_preflight_sha256,
        args.start_utc,
        args.end_utc,
        args.private_output_directory,
    )
    print(json.dumps(result, sort_keys=True))
    if result.get("status") == "aws-dev-residual-cost-audit-failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
