#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-aws-test-create-terraform-plan.py"
SPEC = importlib.util.spec_from_file_location("aws_test_create_terraform_plan", CHECKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-test Terraform plan checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ACCOUNT = "123456789012"
IPV4 = "8.8.8.8"
ROLE = (
    f"arn:aws:iam::{ACCOUNT}:role/"
    "startup-devops-baseline-test-github-runtime-read-role"
)


def plan() -> dict:
    return {
        "format_version": "1.2",
        "variables": {
            "environment": {"value": "test"},
            "project_name": {"value": "startup-devops-baseline"},
            "aws_region": {"value": "us-east-1"},
            "eks_node_min_size": {"value": 4},
            "eks_node_desired_size": {"value": 4},
            "eks_node_max_size": {"value": 4},
            "eks_public_access_cidrs": {"value": ["8.8.8.8/32"]},
            "enable_github_actions_runtime_identity": {"value": False},
            "github_actions_runtime_role_arn": {"value": None},
        },
        "resource_changes": [
            {
                "address": "module.eks.aws_eks_cluster.this",
                "type": "aws_eks_cluster",
                "change": {
                    "actions": ["create"],
                    "after": {
                        "name": "startup-devops-baseline-test",
                        "tags": {"Environment": "test"},
                    },
                },
            },
            {
                "address": "module.vpc.aws_vpc.this",
                "type": "aws_vpc",
                "change": {
                    "actions": ["create"],
                    "after": {"tags_all": {"Environment": "aws-test"}},
                },
            },
            {
                "address": "data.aws_caller_identity.current",
                "type": "aws_caller_identity",
                "change": {"actions": ["read"], "after": {}},
            },
            {
                "address": "data.aws_region.current",
                "type": "aws_region",
                "change": {"actions": ["no-op"], "after": {}},
            },
        ],
    }


class AwsTestCreateTerraformPlanTests(unittest.TestCase):
    def test_valid_create_read_noop_plan_is_accepted(self) -> None:
        result = MODULE.validate(plan(), ACCOUNT, IPV4)
        self.assertEqual(result["status"], "aws-test-create-only-terraform-plan-accepted")
        self.assertEqual(result["action_counts"], {"create": 2, "read": 1, "no-op": 1})
        self.assertEqual(result["aws_test_cluster_create_count"], 1)
        self.assertEqual(result["destroy_actions"], 0)

    def test_update_delete_replacement_unknown_and_empty_are_rejected(self) -> None:
        for actions in (
            ["update"],
            ["delete"],
            ["delete", "create"],
            ["create", "delete"],
            ["forget"],
            [],
        ):
            with self.subTest(actions=actions):
                document = plan()
                document["resource_changes"][1]["change"]["actions"] = actions
                with self.assertRaisesRegex(ValueError, "rejects"):
                    MODULE.validate(document, ACCOUNT, IPV4)

        document = plan()
        document["resource_changes"] = [document["resource_changes"][2]]
        with self.assertRaises(ValueError):
            MODULE.validate(document, ACCOUNT, IPV4)

    def test_fixed_variables_and_management_cidr_are_required(self) -> None:
        for variable, replacement in (
            ("environment", "dev"),
            ("project_name", "other"),
            ("aws_region", "us-west-2"),
            ("eks_node_min_size", 3),
            ("eks_node_desired_size", 3),
            ("eks_node_max_size", 5),
            ("eks_public_access_cidrs", ["1.1.1.1/32"]),
        ):
            with self.subTest(variable=variable):
                document = plan()
                document["variables"][variable]["value"] = replacement
                with self.assertRaisesRegex(ValueError, "variable"):
                    MODULE.validate(document, ACCOUNT, IPV4)

        for address in ("10.0.0.1", "2001:4860:4860::8888", "invalid"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                MODULE.validate(plan(), ACCOUNT, address)

    def test_exact_test_cluster_is_required(self) -> None:
        document = plan()
        document["resource_changes"][0]["change"]["after"]["name"] = (
            "startup-devops-baseline-dev"
        )
        with self.assertRaisesRegex(ValueError, "non-test"):
            MODULE.validate(document, ACCOUNT, IPV4)

        document = plan()
        document["resource_changes"].append(copy.deepcopy(document["resource_changes"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            MODULE.validate(document, ACCOUNT, IPV4)

    def test_foreign_account_arn_and_environment_tag_are_rejected(self) -> None:
        document = plan()
        document["resource_changes"][1]["change"]["after"]["role_arn"] = (
            "arn:aws:iam::999999999999:role/foreign"
        )
        with self.assertRaisesRegex(ValueError, "different AWS account"):
            MODULE.validate(document, ACCOUNT, IPV4)

        document = plan()
        document["resource_changes"][1]["change"]["after"]["tags_all"] = {
            "Environment": "prod"
        }
        with self.assertRaisesRegex(ValueError, "non-test"):
            MODULE.validate(document, ACCOUNT, IPV4)

    def test_optional_runtime_access_entry_is_exact(self) -> None:
        document = plan()
        document["variables"]["enable_github_actions_runtime_identity"]["value"] = True
        document["variables"]["github_actions_runtime_role_arn"]["value"] = ROLE
        document["resource_changes"].append(
            {
                "address": (
                    "module.github_actions_runtime_identity[0]."
                    "aws_eks_access_entry.runtime"
                ),
                "type": "aws_eks_access_entry",
                "change": {
                    "actions": ["create"],
                    "after": {
                        "principal_arn": ROLE,
                        "cluster_name": "startup-devops-baseline-test",
                        "kubernetes_groups": ["demo-api-runtime-qualification"],
                        "tags": {"Environment": "test"},
                    },
                },
            }
        )
        result = MODULE.validate(document, ACCOUNT, IPV4)
        self.assertEqual(result["runtime_access_entry_create_count"], 1)

        for field, replacement in (
            ("principal_arn", "arn:aws:iam::999999999999:role/foreign"),
            ("cluster_name", "startup-devops-baseline-dev"),
            ("kubernetes_groups", ["system:masters"]),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(document)
                changed["resource_changes"][-1]["change"]["after"][field] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(changed, ACCOUNT, IPV4)

    def test_malformed_plan_is_rejected(self) -> None:
        fixtures = (
            [],
            {},
            {"format_version": "1.2", "variables": {}, "resource_changes": {}},
            {"format_version": "1.2", "variables": {}, "resource_changes": [None]},
        )
        for document in fixtures:
            with self.subTest(document=document), self.assertRaises(ValueError):
                MODULE.validate(document, ACCOUNT, IPV4)


if __name__ == "__main__":
    unittest.main()
