#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-aws-dev-create-terraform-plan.py"
SPEC = importlib.util.spec_from_file_location("aws_dev_create_terraform_plan", CHECKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Terraform create-plan checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def plan(*actions: list[str]) -> dict:
    return {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": f"module.fixture.resource.item_{index}",
                "change": {"actions": action},
            }
            for index, action in enumerate(actions)
        ],
    }


class AwsDevCreateTerraformPlanTests(unittest.TestCase):
    def test_create_read_and_noop_are_accepted(self) -> None:
        result = MODULE.validate(plan(["create"], ["read"], ["no-op"]))
        self.assertEqual(result["status"], "aws-dev-create-only-terraform-plan-accepted")
        self.assertEqual(result["action_counts"], {"create": 1, "read": 1, "no-op": 1})
        self.assertEqual(result["destroy_actions"], 0)

    def test_empty_or_no_create_plan_is_rejected(self) -> None:
        for document in (plan(), plan(["read"], ["no-op"])):
            with self.subTest(document=document):
                with self.assertRaisesRegex(ValueError, "at least one create"):
                    MODULE.validate(document)

    def test_delete_update_and_replacement_are_rejected(self) -> None:
        for actions in (["delete"], ["update"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(ValueError, "rejects"):
                    MODULE.validate(plan(["create"], actions))

    def test_unknown_and_combined_actions_are_rejected(self) -> None:
        for actions in (["forget"], ["create", "read"], []):
            with self.subTest(actions=actions):
                with self.assertRaisesRegex(ValueError, "rejects"):
                    MODULE.validate(plan(["create"], actions))

    def test_malformed_plan_is_rejected(self) -> None:
        fixtures = (
            [],
            {},
            {"resource_changes": {}},
            {"resource_changes": [None]},
            {"resource_changes": [{"address": "", "change": {"actions": ["create"]}}]},
            {"resource_changes": [{"address": "x", "change": {"actions": "create"}}]},
        )
        for document in fixtures:
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    MODULE.validate(document)


if __name__ == "__main__":
    unittest.main()
