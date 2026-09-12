#!/usr/bin/env python3
"""Accept only the reviewed nonempty create-only Terraform plan for aws-test."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PLAN_CHECKER = (
    ROOT / "scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py"
)
ALLOWED_ACTIONS = {("create",), ("read",), ("no-op",)}
EXPECTED_CLUSTER = "startup-devops-baseline-test"
EXPECTED_REGION = "us-east-1"
EXPECTED_PROJECT = "startup-devops-baseline"
EXPECTED_ENVIRONMENT = "test"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRIVATE_PLAN = load_module(PRIVATE_PLAN_CHECKER, "aws_test_private_plan")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def variable_value(variables: dict[str, Any], name: str) -> Any:
    entry = variables.get(name)
    require(isinstance(entry, dict) and "value" in entry, f"Plan variable missing: {name}")
    return entry["value"]


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def validate(document: Any, account_id: str, management_ipv4: str) -> dict[str, Any]:
    require(
        isinstance(account_id, str) and re.fullmatch(r"[0-9]{12}", account_id) is not None,
        "Expected AWS account ID must have 12 digits",
    )
    management = PRIVATE_PLAN.ipaddress.ip_address(management_ipv4)
    require(
        management.version == 4 and management.is_global,
        "Expected management address must be a globally routable IPv4",
    )
    expected_cidr = f"{management}/32"

    require(isinstance(document, dict), "Terraform plan JSON must be an object")
    require(isinstance(document.get("format_version"), str), "Terraform plan format_version missing")
    variables = document.get("variables")
    require(isinstance(variables, dict), "Terraform plan variables must be an object")
    expected_variables = {
        "environment": EXPECTED_ENVIRONMENT,
        "project_name": EXPECTED_PROJECT,
        "aws_region": EXPECTED_REGION,
        "eks_node_min_size": 4,
        "eks_node_desired_size": 4,
        "eks_node_max_size": 4,
        "eks_public_access_cidrs": [expected_cidr],
    }
    for name, expected in expected_variables.items():
        require(variable_value(variables, name) == expected, f"Plan variable changed: {name}")

    runtime_enabled = variable_value(variables, "enable_github_actions_runtime_identity")
    runtime_role = variable_value(variables, "github_actions_runtime_role_arn")
    expected_role = (
        f"arn:aws:iam::{account_id}:role/"
        "startup-devops-baseline-test-github-runtime-read-role"
    )
    require(type(runtime_enabled) is bool, "Runtime identity flag must be Boolean")
    require(
        runtime_role is None or runtime_role == expected_role,
        "Runtime identity role differs from the exact aws-test role",
    )
    require(
        not runtime_enabled or runtime_role == expected_role,
        "Enabled runtime identity requires the exact aws-test role",
    )

    changes = document.get("resource_changes")
    require(isinstance(changes, list), "Terraform plan resource_changes must be a list")
    counts = {"create": 0, "read": 0, "no-op": 0}
    clusters: list[dict[str, Any]] = []
    runtime_entries: list[dict[str, Any]] = []
    for index, item in enumerate(changes):
        require(isinstance(item, dict), f"resource_changes[{index}] must be an object")
        address = item.get("address")
        resource_type = item.get("type")
        require(isinstance(address, str) and bool(address), f"resource_changes[{index}] address missing")
        require(isinstance(resource_type, str) and bool(resource_type), f"{address} type missing")
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
            f"Initial aws-test plan rejects {address} actions {actions}",
        )
        counts[actions[0]] += 1

        after = change.get("after")
        if after is not None:
            require(isinstance(after, dict), f"{address} after must be an object or null")
            for candidate in strings(after):
                if candidate.startswith("arn:aws:"):
                    segments = candidate.split(":")
                    require(len(segments) >= 6, f"{address} contains malformed AWS ARN")
                    arn_account = segments[4]
                    require(
                        not arn_account or arn_account in {account_id, "aws"},
                        f"{address} contains a different AWS account",
                    )
            tags = after.get("tags_all") or after.get("tags") or {}
            require(isinstance(tags, dict), f"{address} tags must be an object")
            require(
                tags.get("Environment", "test") in {"test", "aws-test"},
                f"{address} contains a non-test Environment tag",
            )

        if resource_type == "aws_eks_cluster":
            clusters.append(item)
        if resource_type == "aws_eks_access_entry" and address.startswith(
            "module.github_actions_runtime_identity["
        ):
            runtime_entries.append(item)

    require(counts["create"] > 0, "Initial aws-test plan must contain at least one create action")
    require(len(clusters) == 1, "Plan must identify exactly one aws-test EKS cluster")
    cluster_change = clusters[0]["change"]
    require(cluster_change["actions"] == ["create"], "aws-test EKS cluster must be created")
    require(
        isinstance(cluster_change.get("after"), dict)
        and cluster_change["after"].get("name") == EXPECTED_CLUSTER,
        "Plan targets a non-test EKS cluster",
    )

    require(
        len(runtime_entries) == (1 if runtime_enabled else 0),
        "Runtime access-entry inventory differs from the reviewed enable flag",
    )
    if runtime_enabled:
        entry_change = runtime_entries[0]["change"]
        entry = entry_change.get("after")
        require(entry_change["actions"] == ["create"], "Runtime access entry must be created")
        require(isinstance(entry, dict), "Runtime access entry after value missing")
        require(
            entry.get("principal_arn") == expected_role
            and entry.get("cluster_name") == EXPECTED_CLUSTER
            and entry.get("kubernetes_groups") == ["demo-api-runtime-qualification"],
            "Runtime access entry differs from the bounded aws-test mapping",
        )

    return {
        "status": "aws-test-create-only-terraform-plan-accepted",
        "resource_change_count": len(changes),
        "action_counts": counts,
        "aws_test_cluster_create_count": 1,
        "runtime_access_entry_create_count": len(runtime_entries),
        "destroy_actions": 0,
        "replacement_actions": 0,
        "update_actions": 0,
        "unknown_actions": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True, type=Path)
    parser.add_argument("--private-plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        private_plan = json.loads(args.private_plan.read_text())
        PRIVATE_PLAN.validate(private_plan, ROOT)
        result = validate(
            json.loads(args.plan_json.read_text()),
            private_plan["aws_account_id"],
            private_plan["management_ipv4"],
        )
    except (json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"Terraform aws-test create plan rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
