#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py"
SPEC = importlib.util.spec_from_file_location("post_apply_resume", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load post-apply resume executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ACCOUNT = "123456789012"


def fixture() -> tuple[dict, dict, bytes]:
    plan = {
        "resource_changes": [
            {"address": "aws_vpc.main", "change": {"actions": ["create"]}},
            {"address": "aws_subnet.main[0]", "change": {"actions": ["create"]}},
            {"address": "data.aws_iam_policy_document.main", "change": {"actions": ["read"]}},
        ]
    }
    state = {
        "version": 4,
        "resources": [
            {"mode": "managed", "type": "aws_vpc", "name": "main", "instances": [{}]},
            {"mode": "managed", "type": "aws_subnet", "name": "main", "instances": [{"index_key": 0}]},
            {"mode": "data", "type": "aws_iam_policy_document", "name": "main", "instances": [{}]},
            {"mode": "data", "type": "aws_partition", "name": "current", "instances": [{}]},
        ],
    }
    listed = (
        "aws_vpc.main\n"
        "aws_subnet.main[0]\n"
        "data.aws_iam_policy_document.main\n"
        "data.aws_partition.current\n"
    ).encode()
    return plan, state, listed


class StateClassificationTests(unittest.TestCase):
    def test_state_file_requires_600_but_not_a_700_repository_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "repository-directory"
            parent.mkdir(mode=0o755)
            state = parent / "terraform.tfstate"
            state.write_text('{"version":4,"resources":[]}\n')
            state.chmod(0o600)
            MODULE.require_state_hash(state, MODULE.sha256(state))
            state.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "mode must be 600"):
                MODULE.require_state_hash(state, MODULE.sha256(state))

    def test_exact_incident_shape_is_accepted_end_to_end(self) -> None:
        changes = []
        resources = []
        listed = []

        resources.append({
            "mode": "managed", "type": "aws_vpc", "name": "batch",
            "instances": [{"index_key": index} for index in range(20)],
        })
        for index in range(20):
            address = f"aws_vpc.batch[{index}]"
            changes.append({"address": address, "change": {"actions": ["create"]}})
            listed.append(address)
        for index in range(1, 71):
            resource_type = f"aws_fixture_{index}"
            address = f"{resource_type}.item"
            resources.append({
                "mode": "managed", "type": resource_type, "name": "item",
                "instances": [{}],
            })
            changes.append({"address": address, "change": {"actions": ["create"]}})
            listed.append(address)
        for index in range(6):
            address = f"data.aws_iam_policy_document.planned_{index}"
            resources.append({
                "mode": "data", "type": "aws_iam_policy_document",
                "name": f"planned_{index}", "instances": [{}],
            })
            changes.append({"address": address, "change": {"actions": ["read"]}})
            listed.append(address)
        for resource_type, count in MODULE.EXPECTED_UNPLANNED_DATA_TYPES.items():
            name = "extra"
            instances = [{}] if count == 1 else [{"index_key": index} for index in range(count)]
            resources.append({
                "mode": "data", "type": resource_type, "name": name,
                "instances": instances,
            })
            if count == 1:
                listed.append(f"data.{resource_type}.{name}")
            else:
                listed.extend(f"data.{resource_type}.{name}[{index}]" for index in range(count))

        summary = MODULE.classify_state(
            {"resource_changes": changes},
            {"version": 4, "resources": resources},
            ("\n".join(listed) + "\n").encode(),
        )
        MODULE.require_incident_classification(summary)

    def test_classifies_unplanned_data_separately_from_managed_state(self) -> None:
        summary = MODULE.classify_state(*fixture())
        self.assertEqual(summary["missing_planned_create_count"], 0)
        self.assertEqual(summary["unexpected_managed_address_count"], 0)
        self.assertEqual(summary["unexpected_data_address_count"], 1)
        self.assertEqual(summary["unexpected_data_type_counts"], {"aws_partition": 1})
        self.assertEqual(summary["classified_state_list_address_count"], 4)

    def test_missing_planned_create_is_visible(self) -> None:
        plan, state, listed = fixture()
        summary = MODULE.classify_state(plan, state, listed.replace(b"aws_vpc.main\n", b""))
        self.assertEqual(summary["missing_planned_create_count"], 1)

    def test_unplanned_managed_address_is_never_accepted(self) -> None:
        plan, state, listed = fixture()
        state["resources"].append(
            {"mode": "managed", "type": "aws_s3_bucket", "name": "foreign", "instances": [{}]}
        )
        summary = MODULE.classify_state(plan, state, listed + b"aws_s3_bucket.foreign\n")
        self.assertEqual(summary["unexpected_managed_address_count"], 1)

    def test_incident_contract_requires_exact_aggregate_and_data_types(self) -> None:
        accepted = {
            "plan_resource_change_count": 96,
            "plan_create_address_count": 90,
            "state_list_address_count": 103,
            "state_resource_block_count": 80,
            "state_resource_instance_count": 103,
            "classified_state_list_address_count": 103,
            "missing_planned_create_count": 0,
            "unexpected_state_address_count": 7,
            "unexpected_managed_address_count": 0,
            "unexpected_data_address_count": 7,
            "unexpected_unclassified_address_count": 0,
            "unexpected_data_type_counts": dict(MODULE.EXPECTED_UNPLANNED_DATA_TYPES),
        }
        MODULE.require_incident_classification(accepted)
        changed = dict(accepted)
        changed["unexpected_data_type_counts"] = {"aws_partition": 7}
        with self.assertRaisesRegex(ValueError, "classification"):
            MODULE.require_incident_classification(changed)


class ResumeExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name) / "private"
        self.parent.mkdir(mode=0o700)
        self.output = self.parent / "resume"
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.context = {
            "expected_current_main": "f" * 40,
            "account_id": ACCOUNT,
            "management_cidr": "8.8.8.8/32",
            "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
            "remaining": 10000,
            "classification": {
                "plan_create_address_count": 90,
                "missing_planned_create_count": 0,
                "unexpected_managed_address_count": 0,
                "unexpected_data_address_count": 7,
                "state_list_address_count": 103,
            },
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def environment(self, **extra):
        values = {
            "AWS_ENVIRONMENT": "aws-test",
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_TEST_POST_APPLY_RESUME": MODULE.RESUME_CONFIRMATION,
        }
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=True)

    def runner(self, arguments, environment, timeout):
        self.calls.append((arguments, environment))
        joined = " ".join(arguments)
        if "get-caller-identity" in joined:
            body = {"Account": ACCOUNT}
        elif "list-clusters" in joined:
            body = {"clusters": [MODULE.CLUSTER_NAME]}
        elif "describe-cluster" in joined:
            body = {
                "cluster": {
                    "name": MODULE.CLUSTER_NAME,
                    "status": "ACTIVE",
                    "resourcesVpcConfig": {"publicAccessCidrs": ["8.8.8.8/32"]},
                }
            }
        elif "describe-secret" in joined:
            body = {"Name": MODULE.SECRET_NAME}
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")

    def test_redacted_verify_keeps_resume_unauthorized(self) -> None:
        result = MODULE.redacted_verification(self.context)
        self.assertEqual(result["commands_executed"], [])
        self.assertFalse(result["resume_execution_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])

    def test_execute_completes_only_read_only_post_apply_checks(self) -> None:
        with self.environment():
            result = MODULE.execute(self.context, self.output, self.runner)
        self.assertEqual(result["status"], "aws-test-post-apply-resume-verification-complete")
        self.assertTrue(result["prior_terraform_apply_succeeded"])
        self.assertFalse(result["terraform_apply_reexecuted"])
        self.assertFalse(result["resume_aws_mutation_executed"])
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(arguments[0] == "aws" for arguments, _ in self.calls))
        self.assertFalse(any("terraform" in arguments for arguments, _ in self.calls))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_confirmation_or_prior_apply_control_stops_before_commands(self) -> None:
        with self.environment(CONFIRM_AWS_TEST_POST_APPLY_RESUME=""), self.assertRaisesRegex(ValueError, "confirmation"):
            MODULE.execute(self.context, self.output, self.runner)
        self.assertEqual(self.calls, [])
        with self.environment(CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION="polluted"), self.assertRaisesRegex(ValueError, "must be unset"):
            MODULE.execute(self.context, self.output, self.runner)
        self.assertEqual(self.calls, [])

    def test_environment_removes_endpoint_overrides(self) -> None:
        with self.environment(AWS_ENDPOINT_URL="https://invalid", AWS_PROFILE="reviewed"):
            MODULE.execute(self.context, self.output, self.runner)
        for _, environment in self.calls:
            self.assertNotIn("AWS_ENDPOINT_URL", environment)
            self.assertEqual(environment["AWS_PROFILE"], "reviewed")

    def test_wrong_cluster_inventory_fails_closed(self) -> None:
        def runner(arguments, environment, timeout):
            if "list-clusters" in arguments:
                return subprocess.CompletedProcess(arguments, 0, b'{"clusters":[]}', b"")
            return self.runner(arguments, environment, timeout)
        with self.environment(), self.assertRaisesRegex(ValueError, "only the aws-test"):
            MODULE.execute(self.context, self.output, runner)

    def test_cluster_cidr_drift_fails_before_secret(self) -> None:
        def runner(arguments, environment, timeout):
            if "describe-cluster" in arguments:
                body = {"cluster": {"name": MODULE.CLUSTER_NAME, "status": "ACTIVE", "resourcesVpcConfig": {"publicAccessCidrs": ["1.1.1.1/32"]}}}
                return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")
            return self.runner(arguments, environment, timeout)
        with self.environment(), self.assertRaisesRegex(ValueError, "public CIDR"):
            MODULE.execute(self.context, self.output, runner)

    def test_secret_tombstone_fails_closed(self) -> None:
        def runner(arguments, environment, timeout):
            if "describe-secret" in arguments:
                body = {"Name": MODULE.SECRET_NAME, "DeletedDate": "later"}
                return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")
            return self.runner(arguments, environment, timeout)
        with self.environment(), self.assertRaisesRegex(ValueError, "pending deletion"):
            MODULE.execute(self.context, self.output, runner)


if __name__ == "__main__":
    unittest.main()
