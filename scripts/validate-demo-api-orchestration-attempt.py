#!/usr/bin/env python3
"""Validate one v0.10.7 orchestration Attempt artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_api_orchestration_attempt import validate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True, type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.attempt.read_text())
        validate(document)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Orchestration Attempt validation passed: {args.attempt}")


if __name__ == "__main__":
    main()
