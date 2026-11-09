#!/usr/bin/env python3
"""Accept only the exact create-only Terraform state-bootstrap plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


EXPECTED_MANAGED_ADDRESSES = {
    'aws_iam_policy.root_state_access["bootstrap"]',
    'aws_iam_policy.root_state_access["runtime-identities"]',
    'aws_iam_policy.root_state_access["dev"]',
    'aws_iam_policy.root_state_access["test"]',
    'aws_iam_policy.root_state_access["prod"]',
    "aws_kms_alias.state",
    "aws_kms_key.state",
    "aws_s3_bucket.state",
    "aws_s3_bucket_ownership_controls.state",
    "aws_s3_bucket_policy.state",
    "aws_s3_bucket_public_access_block.state",
    "aws_s3_bucket_server_side_encryption_configuration.state",
    "aws_s3_bucket_versioning.state",
}

ALLOWED_DATA_ADDRESSES = {
    "data.aws_caller_identity.current",
    "data.aws_partition.current",
    "data.aws_iam_policy_document.kms",
    "data.aws_iam_policy_document.bucket",
    'data.aws_iam_policy_document.root_state_access["bootstrap"]',
    'data.aws_iam_policy_document.root_state_access["runtime-identities"]',
    'data.aws_iam_policy_document.root_state_access["dev"]',
    'data.aws_iam_policy_document.root_state_access["test"]',
    'data.aws_iam_policy_document.root_state_access["prod"]',
}

EXPECTED_POLICY_ROOTS = (
    "bootstrap",
    "runtime-identities",
    "dev",
    "test",
    "prod",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def variable_value(variables: dict[str, Any], name: str) -> Any:
    entry = variables.get(name)
    require(isinstance(entry, dict) and "value" in entry, f"Plan variable missing: {name}")
    return entry["value"]


def resource_after(changes: dict[str, dict[str, Any]], address: str) -> dict[str, Any]:
    item = changes[address]
    change = item.get("change")
    require(isinstance(change, dict), f"{address} change must be an object")
    after = change.get("after")
    require(isinstance(after, dict), f"{address} planned value missing")
    return after


def one_block(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, list) and len(value) == 1, f"{label} must contain one block")
    require(isinstance(value[0], dict), f"{label} block must be an object")
    return value[0]


def validate(
    document: Any,
    *,
    expected_bucket_name: str,
    expected_kms_alias: str,
    expected_additional_tags: dict[str, str],
) -> dict[str, Any]:
    require(
        isinstance(expected_bucket_name, str)
        and 3 <= len(expected_bucket_name) <= 63
        and re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", expected_bucket_name) is not None,
        "Expected bucket name is invalid",
    )
    require(
        isinstance(expected_kms_alias, str)
        and expected_kms_alias.startswith("alias/")
        and len(expected_kms_alias) > 6,
        "Expected KMS alias is invalid",
    )
    require(
        isinstance(expected_additional_tags, dict)
        and all(
            isinstance(key, str) and key and isinstance(value, str) and value
            for key, value in expected_additional_tags.items()
        ),
        "Expected additional tags must be a non-empty string map",
    )
    require(isinstance(document, dict), "Terraform plan JSON must be an object")
    require(isinstance(document.get("format_version"), str), "Terraform plan format_version missing")

    variables = document.get("variables")
    require(isinstance(variables, dict), "Terraform plan variables must be an object")
    expected_variables = {
        "aws_region": "us-east-1",
        "project_name": "startup-devops-baseline",
        "state_bucket_name": expected_bucket_name,
        "state_kms_alias": expected_kms_alias,
        "additional_tags": expected_additional_tags,
    }
    for name, expected in expected_variables.items():
        require(variable_value(variables, name) == expected, f"Plan variable changed: {name}")

    raw_changes = document.get("resource_changes")
    require(isinstance(raw_changes, list), "Terraform plan resource_changes must be a list")
    changes: dict[str, dict[str, Any]] = {}
    managed: set[str] = set()
    data: set[str] = set()
    counts = {"create": 0, "read": 0, "no-op": 0}

    for index, item in enumerate(raw_changes):
        require(isinstance(item, dict), f"resource_changes[{index}] must be an object")
        address = item.get("address")
        mode = item.get("mode")
        resource_type = item.get("type")
        require(isinstance(address, str) and address, f"resource_changes[{index}] address missing")
        require(address not in changes, f"Duplicate resource address: {address}")
        require(mode in {"managed", "data"}, f"{address} has an unknown mode")
        require(isinstance(resource_type, str) and resource_type, f"{address} type missing")
        change = item.get("change")
        require(isinstance(change, dict), f"{address} change must be an object")
        actions = change.get("actions")
        require(
            isinstance(actions, list) and all(isinstance(action, str) for action in actions),
            f"{address} actions must be a string list",
        )
        require(change.get("importing") is None, f"{address} import is forbidden")

        if mode == "managed":
            require(address in EXPECTED_MANAGED_ADDRESSES, f"Unexpected managed resource: {address}")
            require(actions == ["create"], f"{address} must be create-only")
            managed.add(address)
        else:
            require(address in ALLOWED_DATA_ADDRESSES, f"Unexpected data resource: {address}")
            require(actions in (["read"], ["no-op"]), f"{address} data action is forbidden")
            data.add(address)

        counts[actions[0]] += 1
        changes[address] = item

    require(managed == EXPECTED_MANAGED_ADDRESSES, "Managed resource inventory changed")

    bucket = resource_after(changes, "aws_s3_bucket.state")
    require(bucket.get("bucket") == expected_bucket_name, "State bucket name changed")
    require(bucket.get("force_destroy") is False, "State bucket force_destroy must be false")

    kms = resource_after(changes, "aws_kms_key.state")
    require(kms.get("enable_key_rotation") is True, "KMS rotation must be enabled")
    require(kms.get("deletion_window_in_days") == 30, "KMS deletion window changed")

    alias = resource_after(changes, "aws_kms_alias.state")
    require(alias.get("name") == expected_kms_alias, "KMS alias changed")

    ownership = resource_after(changes, "aws_s3_bucket_ownership_controls.state")
    ownership_rule = one_block(ownership.get("rule"), "S3 ownership rule")
    require(
        ownership_rule.get("object_ownership") == "BucketOwnerEnforced",
        "S3 ownership control changed",
    )

    public = resource_after(changes, "aws_s3_bucket_public_access_block.state")
    for field in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        require(public.get(field) is True, f"S3 public-access control changed: {field}")

    versioning = resource_after(changes, "aws_s3_bucket_versioning.state")
    versioning_configuration = one_block(
        versioning.get("versioning_configuration"),
        "S3 versioning configuration",
    )
    require(versioning_configuration.get("status") == "Enabled", "S3 versioning is not enabled")

    encryption = resource_after(
        changes,
        "aws_s3_bucket_server_side_encryption_configuration.state",
    )
    encryption_rule = one_block(encryption.get("rule"), "S3 encryption rule")
    require(encryption_rule.get("bucket_key_enabled") is True, "S3 Bucket Key is disabled")
    encryption_default = one_block(
        encryption_rule.get("apply_server_side_encryption_by_default"),
        "S3 default encryption",
    )
    require(encryption_default.get("sse_algorithm") == "aws:kms", "S3 encryption is not SSE-KMS")

    for root in EXPECTED_POLICY_ROOTS:
        address = f'aws_iam_policy.root_state_access["{root}"]'
        policy = resource_after(changes, address)
        require(
            policy.get("name") == f"startup-devops-baseline-terraform-state-{root}",
            f"IAM policy name changed: {root}",
        )

    prior = document.get("prior_state")
    if prior is not None:
        require(isinstance(prior, dict), "Terraform prior_state must be an object")
        values = prior.get("values")
        if values is not None:
            require(isinstance(values, dict), "Terraform prior_state values must be an object")
            root_module = values.get("root_module")
            if root_module is not None:
                require(isinstance(root_module, dict), "Terraform prior root module must be an object")

                def require_no_managed_prior(module: dict[str, Any]) -> None:
                    prior_resources = module.get("resources", [])
                    require(isinstance(prior_resources, list), "Terraform prior resources must be a list")
                    require(
                        not any(
                            item.get("mode") == "managed"
                            for item in prior_resources
                            if isinstance(item, dict)
                        ),
                        "Initial state-bootstrap plan requires empty managed prior state",
                    )
                    children = module.get("child_modules", [])
                    require(isinstance(children, list), "Terraform prior child modules must be a list")
                    for child in children:
                        require(isinstance(child, dict), "Terraform prior child module must be an object")
                        require_no_managed_prior(child)

                require_no_managed_prior(root_module)

    return {
        "status": "state-bootstrap-create-only-terraform-plan-accepted",
        "managed_create_count": len(managed),
        "data_change_count": len(data),
        "resource_change_count": len(raw_changes),
        "action_counts": counts,
        "destroy_actions": 0,
        "replacement_actions": 0,
        "update_actions": 0,
        "import_actions": 0,
        "unexpected_managed_resources": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True, type=Path)
    parser.add_argument("--private-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(args.private_request.read_text())
        inputs = request["expectedInputs"]
        result = validate(
            json.loads(args.plan_json.read_text()),
            expected_bucket_name=inputs["stateBucketName"],
            expected_kms_alias=inputs["stateKmsAlias"],
            expected_additional_tags=inputs["additionalTags"],
        )
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"State-bootstrap Terraform plan rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
