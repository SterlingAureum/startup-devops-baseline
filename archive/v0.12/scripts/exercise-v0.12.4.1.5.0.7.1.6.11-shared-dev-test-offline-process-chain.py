#!/usr/bin/env python3
"""Run the complete shared dev/test teardown chain through fresh offline processes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import aws_two_wave_teardown_offline_process_chain as CHAIN


ROOT = Path(__file__).resolve().parents[1]
CONFIRMATION = "run-sixteen-synthetic-fixed-fake-phase-processes"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--confirm", required=True)
    return value


def run(argv: list[str] | None = None) -> dict:
    args = parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        raise CHAIN.OfflineProcessChainStopped("exact-confirmation-required")
    return CHAIN.run_offline_process_chain(repository_root=ROOT)


def main() -> int:
    try:
        result = run()
    except (CHAIN.OfflineProcessChainStopped, OSError, TypeError, ValueError):
        parser().exit(
            1,
            "STOP: shared dev/test offline process chain failed; temporary stores were removed and no retry was performed.\n",
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
