#!/usr/bin/env python3
"""Guard the destructive aws-dev wrapper with reviewed, fresh evidence."""

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
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts/preflight-v0.11.9.3.6.6.5-aws-dev-teardown.py"
DESTROY_PATH = ROOT / "scripts/destroy-aws-dev.sh"
EXECUTION_CONFIRMATION = "execute-reviewed-aws-dev-teardown"
MAXIMUM_WINDOW_SECONDS = 14400
MINIMUM_REMAINING_SECONDS = 900

spec = importlib.util.spec_from_file_location("aws_dev_teardown_preflight", PREFLIGHT_PATH)
assert spec and spec.loader
PREFLIGHT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREFLIGHT)

Preflight = Callable[[str], dict[str, object]]
Destroy = Callable[[], int]


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Teardown window timestamps must be UTC")
    return parsed.astimezone(timezone.utc)


def require_private_result(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Reviewed preflight result must be a regular file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Reviewed preflight result mode must be 600")
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError("Reviewed preflight directory must be private")
    return json.loads(path.read_text())


def default_destroy() -> int:
    env = os.environ.copy()
    env["AWS_ENVIRONMENT"] = "aws-dev"
    env["CONFIRM_AWS_ENVIRONMENT_DESTROY"] = "destroy-with-backups"
    result = subprocess.run(
        [str(DESTROY_PATH)], cwd=ROOT, env=env,
        stdout=sys.stderr, stderr=sys.stderr, check=False,
    )
    return result.returncode


def execute(
    mode: str,
    expected_commit: str,
    preflight_path: Path,
    expected_preflight_sha256: str,
    start_utc: str,
    end_utc: str,
    *,
    now: datetime | None = None,
    preflight: Preflight = PREFLIGHT.execute,
    destroy: Destroy = default_destroy,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_preflight_sha256):
        raise ValueError("Expected preflight SHA must be a lowercase SHA-256")
    data = preflight_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_preflight_sha256:
        raise ValueError("Reviewed preflight result fingerprint changed")
    reviewed = require_private_result(preflight_path)
    if reviewed.get("control_plane_commit") != expected_commit:
        raise ValueError("Reviewed preflight commit does not match execution commit")
    if reviewed.get("status") != "aws-dev-teardown-preflight-ready-for-separate-approval":
        raise ValueError("Reviewed preflight did not reach the ready state")
    for key in ("execution_authorized", "teardown_authorized", "mutation_executed"):
        if reviewed.get(key) is not False:
            raise ValueError(f"Reviewed preflight boundary changed: {key}")

    start = parse_utc(start_utc)
    end = parse_utc(end_utc)
    current = now or datetime.now(timezone.utc)
    duration = int((end - start).total_seconds())
    remaining = int((end - current).total_seconds())
    if duration <= 0 or duration > MAXIMUM_WINDOW_SECONDS:
        raise ValueError("Teardown window must be positive and no longer than four hours")
    if current < start or current >= end or remaining < MINIMUM_REMAINING_SECONDS:
        raise ValueError("Current time is outside the reviewed teardown execution window")

    immediate = preflight(expected_commit)
    if immediate != reviewed:
        raise ValueError("Immediate preflight does not match the reviewed result")

    common = {
        "control_plane_commit": expected_commit,
        "reviewed_preflight_sha256": expected_preflight_sha256,
        "remaining_window_seconds": remaining,
        "immediate_preflight_matched": True,
        "target_environment": "aws-dev",
        "aws_test_created": False,
        "residual_cost_audit_executed": False,
    }
    if mode == "verify":
        return {
            **common,
            "status": "aws-dev-teardown-execution-inputs-verified",
            "execution_authorized": False,
            "teardown_executed": False,
            "next_action": "obtain-separate-aws-dev-teardown-execution-approval",
        }
    if mode != "execute":
        raise ValueError("Mode must be verify or execute")
    if os.environ.get("CONFIRM_AWS_DEV_TEARDOWN_EXECUTION") != EXECUTION_CONFIRMATION:
        raise ValueError("Separate aws-dev teardown execution confirmation is required")
    if os.environ.get("CONFIRM_AWS_ENVIRONMENT_DESTROY"):
        raise ValueError("Caller must not set the underlying destroy confirmation")
    exit_code = destroy()
    if exit_code:
        raise RuntimeError(f"aws-dev teardown failed with exit code {exit_code}")
    return {
        **common,
        "status": "aws-dev-teardown-execution-complete",
        "execution_authorized": True,
        "teardown_executed": True,
        "destroy_exit_code": 0,
        "next_action": "run-and-review-separate-aws-dev-residual-cost-audit",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    parser.add_argument("--preflight-result", required=True, type=Path)
    parser.add_argument("--expected-preflight-sha256", required=True)
    parser.add_argument("--start-utc", required=True)
    parser.add_argument("--end-utc", required=True)
    args = parser.parse_args()
    result = execute(
        args.mode, args.expected_control_plane_commit, args.preflight_result,
        args.expected_preflight_sha256, args.start_utc, args.end_utc,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
