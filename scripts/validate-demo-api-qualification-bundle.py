#!/usr/bin/env python3
"""Validate one durable v0.10.5 qualification bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from demo_api_qualification_bundle import utc, validate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--now")
    parser.add_argument("--allow-expired", action="store_true")
    parser.add_argument("--minimum-remaining-seconds", type=int, default=0)
    args = parser.parse_args()
    now = utc(args.now) if args.now else datetime.now(timezone.utc)
    try:
        document = json.loads(args.bundle.read_text())
        validate(document, root=args.root, now=now, require_fresh=not args.allow_expired)
        if not args.allow_expired and args.minimum_remaining_seconds:
            remaining = (utc(document["expiresAt"]) - now).total_seconds()
            if remaining < args.minimum_remaining_seconds:
                raise ValueError(
                    "Qualification bundle does not have the required remaining validity."
                )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Qualification bundle validation passed: {args.bundle}")


if __name__ == "__main__":
    main()
