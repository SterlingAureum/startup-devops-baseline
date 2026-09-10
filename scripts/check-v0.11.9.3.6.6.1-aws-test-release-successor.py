#!/usr/bin/env python3
"""Accept only the reviewed pre-promotion or promoted aws-test release bytes."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ALLOWED = {
    "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22": "historical-aws-test",
    "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46": "reviewed-promoted-candidate",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-file", required=True, type=Path)
    args = parser.parse_args()
    digest = hashlib.sha256(args.release_file.read_bytes()).hexdigest()
    state = ALLOWED.get(digest)
    if state is None:
        parser.exit(1, f"Unreviewed aws-test release identity: {digest}\n")
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
