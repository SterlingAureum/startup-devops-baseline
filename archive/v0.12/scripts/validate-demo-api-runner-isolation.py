#!/usr/bin/env python3
"""Validate GitHub run/job fixtures and write runner-isolation facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_api_runner_isolation import validate


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--environment", required=True, choices=("aws-dev", "aws-test"))
    parser.add_argument("--interrupted-run-id", required=True)
    parser.add_argument("--resumed-run-id", required=True)
    parser.add_argument("--interrupted-run", required=True, type=Path)
    parser.add_argument("--interrupted-jobs", required=True, type=Path)
    parser.add_argument("--resumed-run", required=True, type=Path)
    parser.add_argument("--resumed-jobs", required=True, type=Path)
    parser.add_argument("--registered-runners", required=True, type=Path)
    parser.add_argument("--allow-registered", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = validate(
        repository=args.repository,
        environment=args.environment,
        interrupted_run_id=args.interrupted_run_id,
        resumed_run_id=args.resumed_run_id,
        interrupted_run=load(args.interrupted_run),
        interrupted_jobs=load(args.interrupted_jobs),
        resumed_run=load(args.resumed_run),
        resumed_jobs=load(args.resumed_jobs),
        registered_runners=load(args.registered_runners),
        require_unregistered=not args.allow_registered,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Runner isolation passed: {args.output}")


if __name__ == "__main__":
    main()
