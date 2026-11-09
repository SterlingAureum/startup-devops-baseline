#!/usr/bin/env python3
"""Write one repository-bound v0.10 final clean-room acceptance record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from v010_final_evidence import build_document, canonical_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    source = json.loads(args.input.read_text())
    observed_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if source.get("validatedControlPlaneSha") != observed_head:
        raise SystemExit("Input validatedControlPlaneSha must equal the checked-out commit.")
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    allowed_output = args.output.resolve()
    unexpected = []
    for line in status:
        raw = line[3:]
        candidate = (root / raw).resolve()
        if candidate != allowed_output:
            unexpected.append(line)
    if unexpected:
        raise SystemExit("Final evidence must be written from a clean reviewed main worktree.")

    document = build_document(source, root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(document))
    print(args.output)


if __name__ == "__main__":
    main()
