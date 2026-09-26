#!/usr/bin/env python3
"""Offline tests for the post-apply refresh-state recovery."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("post_apply_recovery_under_test", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load recovery executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load_executor()


def resource(mode: str, resource_type: str, name: str, attributes: dict) -> dict:
    return {
        "mode": mode,
        "type": resource_type,
        "name": name,
        "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
        "instances": [{"schema_version": 0, "attributes": attributes, "sensitive_attributes": []}],
    }


def address(item: dict) -> str:
    prefix = "data." if item["mode"] == "data" else ""
    return f"{prefix}{item['type']}.{item['name']}"


def fixture():
    managed = [resource("managed", "test_managed", f"r{i}", {"value": i, "tags": None}) for i in range(13)]
    data = [resource("data", "test_data", f"d{i}", {"value": i}) for i in range(8)]
    caller = resource("data", "aws_caller_identity", "current", {
        "account_id": "123456789012", "arn": "arn:old", "id": "123456789012", "user_id": "old",
    })
    before = {
        "version": 4, "terraform_version": "1.14.5", "serial": 1, "lineage": "lineage",
        "outputs": {"stable": {"value": "ok", "type": "string"}},
        "resources": managed + data + [caller], "check_results": [],
    }
    after = copy.deepcopy(before)
    after["serial"] = 2
    for item in after["resources"][:7]:
        item["instances"][0]["attributes"]["tags"] = {}
    after["resources"][-1]["instances"][0]["attributes"]["arn"] = "arn:new"
    after["resources"][-1]["instances"][0]["attributes"]["user_id"] = "new"
    drift = []
    for item in after["resources"][:7]:
        drift.append({
            "address": address(item), "mode": "managed", "type": item["type"], "name": item["name"],
            "change": {"actions": ["update"], "before": None, "after": copy.deepcopy(item["instances"][0]["attributes"])},
        })
    plan = {
        "planned_values": {"root_module": {}}, "resource_changes": [], "resource_drift": drift,
        "output_changes": {f"o{i}": {"actions": ["no-op"]} for i in range(7)},
    }
    shown_resources = []
    for item in after["resources"]:
        shown_resources.append({
            "address": address(item), "mode": item["mode"], "type": item["type"],
            "name": item["name"], "values": copy.deepcopy(item["instances"][0]["attributes"]),
        })
    state_show = {"values": {"root_module": {"resources": shown_resources}}}
    managed_addresses, data_addresses = E.BASE.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(before)
    context = {
        "plan": plan, "managed": managed_addresses, "data": data_addresses,
        "request": {"expectedAwsAccountId": "123456789012"},
    }
    return context, before, after, state_show


class IncidentValidationTests(unittest.TestCase):
    def validate(self, context, before, after, state_show):
        original = E.BASE.load_json
        values = iter((before, after, state_show))
        E.BASE.load_json = lambda *_args, **_kwargs: next(values)
        try:
            return E.validate_incident(context, Path("/unused"))
        finally:
            E.BASE.load_json = original

    def test_exact_reviewed_transition_is_accepted(self):
        context, before, after, state_show = fixture()
        result = self.validate(context, before, after, state_show)
        self.assertEqual(len(result["drift"]), 7)
        self.assertEqual(result["after"]["serial"], 2)

    def test_unreviewed_managed_change_is_rejected(self):
        context, before, after, state_show = fixture()
        after["resources"][8]["instances"][0]["attributes"]["value"] = 999
        with self.assertRaisesRegex(ValueError, "changed-instance inventory"):
            self.validate(context, before, after, state_show)

    def test_caller_account_change_is_rejected(self):
        context, before, after, state_show = fixture()
        after["resources"][-1]["instances"][0]["attributes"]["account_id"] = "999999999999"
        with self.assertRaisesRegex(ValueError, "outside arn/user_id"):
            self.validate(context, before, after, state_show)

    def test_caller_extra_field_change_is_rejected(self):
        context, before, after, state_show = fixture()
        after["resources"][-1]["instances"][0]["attributes"]["id"] = "changed"
        with self.assertRaisesRegex(ValueError, "outside arn/user_id"):
            self.validate(context, before, after, state_show)

    def test_reviewed_after_value_mismatch_is_rejected(self):
        context, before, after, state_show = fixture()
        context["plan"]["resource_drift"][0]["change"]["after"]["tags"] = {"unexpected": "value"}
        with self.assertRaisesRegex(ValueError, "Reviewed drift after-value changed"):
            self.validate(context, before, after, state_show)

    def test_persisted_show_mismatch_is_rejected(self):
        context, before, after, state_show = fixture()
        state_show["values"]["root_module"]["resources"][0]["values"]["tags"] = {"unexpected": "value"}
        with self.assertRaisesRegex(ValueError, "Persisted state-show values"):
            self.validate(context, before, after, state_show)

    def test_nonempty_planned_root_is_rejected(self):
        context, before, after, state_show = fixture()
        context["plan"]["planned_values"]["root_module"] = {"resources": []}
        with self.assertRaisesRegex(ValueError, "planned root representation"):
            self.validate(context, before, after, state_show)


if __name__ == "__main__":
    unittest.main(verbosity=2)
