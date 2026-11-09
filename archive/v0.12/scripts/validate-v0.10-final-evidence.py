#!/usr/bin/env python3
"""Validate one repository-bound v0.10 final acceptance record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from v010_final_evidence import verify_references


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.evidence.read_text())
    verify_references(document, args.root.resolve())
    print(f"v0.10 final acceptance evidence passed: {args.evidence}")


if __name__ == "__main__":
    main()
