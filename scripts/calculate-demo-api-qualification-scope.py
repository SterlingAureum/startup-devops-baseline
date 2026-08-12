#!/usr/bin/env python3
"""CLI for deterministic demo-api qualification-scope calculation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from demo_api_qualification_scope import calculate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    value = calculate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    if args.github_output:
        with args.github_output.open("a") as output:
            output.write(f"scope-sha256={value['scopeSha256']}\n")
            output.write(f"contract-sha256={value['contractSha256']}\n")
    print(value["scopeSha256"])


if __name__ == "__main__":
    main()
