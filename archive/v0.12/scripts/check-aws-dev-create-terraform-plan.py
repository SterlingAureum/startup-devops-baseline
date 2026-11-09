#!/usr/bin/env python3
"""Accept only a nonempty, create-only Terraform plan for initial aws-dev."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_ACTIONS = {("create",), ("read",), ("no-op",)}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(document: Any) -> dict[str, Any]:
    require(isinstance(document, dict), "Terraform plan JSON must be an object")
    changes = document.get("resource_changes")
    require(isinstance(changes, list), "Terraform plan resource_changes must be a list")

    counts = {"create": 0, "read": 0, "no-op": 0}
    for index, item in enumerate(changes):
        require(isinstance(item, dict), f"resource_changes[{index}] must be an object")
        address = item.get("address")
        require(isinstance(address, str) and bool(address), f"resource_changes[{index}] address missing")
        change = item.get("change")
        require(isinstance(change, dict), f"{address} change must be an object")
        actions = change.get("actions")
        require(
            isinstance(actions, list) and all(isinstance(action, str) for action in actions),
            f"{address} actions must be a string list",
        )
        action_tuple = tuple(actions)
        require(
            action_tuple in ALLOWED_ACTIONS,
            f"Initial aws-dev plan rejects {address} actions {actions}",
        )
        counts[actions[0]] += 1

    require(counts["create"] > 0, "Initial aws-dev plan must contain at least one create action")
    return {
        "status": "aws-dev-create-only-terraform-plan-accepted",
        "resource_change_count": len(changes),
        "action_counts": counts,
        "destroy_actions": 0,
        "replacement_actions": 0,
        "update_actions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate(json.loads(args.plan_json.read_text()))
    except (json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"Terraform create plan rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
