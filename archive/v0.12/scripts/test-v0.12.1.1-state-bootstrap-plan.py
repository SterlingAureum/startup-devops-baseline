#!/usr/bin/env python3
"""Offline tests for the v0.12.1.1 state-bootstrap plan-only checkpoint."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = load_module(
    ROOT / "scripts/check-v0.12.1.1-state-bootstrap-terraform-plan.py",
    "state_bootstrap_gate_tests",
)
EXECUTOR = load_module(
    ROOT / "scripts/execute-v0.12.1.1-state-bootstrap-plan.py",
    "state_bootstrap_executor_tests",
)

BUCKET = "startup-devops-baseline-state-example-1"
ALIAS = "alias/startup-devops-baseline-terraform-state"
TAGS = {"Owner": "platform", "Repository": "startup-devops-baseline"}
MAIN_SHA = "a" * 40
ACCOUNT = "123456" + "789012"
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def change(address: str, resource_type: str, after: dict, *, mode: str = "managed") -> dict:
    return {
        "address": address,
        "mode": mode,
        "type": resource_type,
        "name": address.rsplit(".", 1)[-1].split("[")[0],
        "change": {
            "actions": ["create"] if mode == "managed" else ["read"],
            "before": None,
            "after": after,
            "after_unknown": {},
        },
    }


def valid_plan() -> dict:
    resources = [
        change("aws_kms_key.state", "aws_kms_key", {
            "deletion_window_in_days": 30,
            "enable_key_rotation": True,
        }),
        change("aws_kms_alias.state", "aws_kms_alias", {"name": ALIAS}),
        change("aws_s3_bucket.state", "aws_s3_bucket", {
            "bucket": BUCKET,
            "force_destroy": False,
        }),
        change("aws_s3_bucket_ownership_controls.state", "aws_s3_bucket_ownership_controls", {
            "rule": [{"object_ownership": "BucketOwnerEnforced"}],
        }),
        change("aws_s3_bucket_public_access_block.state", "aws_s3_bucket_public_access_block", {
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True,
        }),
        change("aws_s3_bucket_versioning.state", "aws_s3_bucket_versioning", {
            "versioning_configuration": [{"status": "Enabled"}],
        }),
        change(
            "aws_s3_bucket_server_side_encryption_configuration.state",
            "aws_s3_bucket_server_side_encryption_configuration",
            {
                "rule": [{
                    "bucket_key_enabled": True,
                    "apply_server_side_encryption_by_default": [{
                        "kms_master_key_id": None,
                        "sse_algorithm": "aws:kms",
                    }],
                }],
            },
        ),
        change("aws_s3_bucket_policy.state", "aws_s3_bucket_policy", {"policy": None}),
    ]
    for root in ("bootstrap", "runtime-identities", "dev", "test", "prod"):
        resources.append(
            change(
                f'aws_iam_policy.root_state_access["{root}"]',
                "aws_iam_policy",
                {"name": f"startup-devops-baseline-terraform-state-{root}", "policy": None},
            )
        )
    resources.append(
        change(
            "data.aws_caller_identity.current",
            "aws_caller_identity",
            {},
            mode="data",
        )
    )
    return {
        "format_version": "1.2",
        "terraform_version": "1.16.3",
        "variables": {
            "aws_region": {"value": "us-east-1"},
            "project_name": {"value": "startup-devops-baseline"},
            "state_bucket_name": {"value": BUCKET},
            "state_kms_alias": {"value": ALIAS},
            "additional_tags": {"value": TAGS},
        },
        "resource_changes": resources,
        "prior_state": {"values": {"root_module": {"resources": []}}},
    }


def gate(plan: dict) -> dict:
    return GATE.validate(
        plan,
        expected_bucket_name=BUCKET,
        expected_kms_alias=ALIAS,
        expected_additional_tags=TAGS,
    )


class PlanGateTests(unittest.TestCase):
    def test_accepts_exact_create_only_plan(self) -> None:
        result = gate(valid_plan())
        self.assertEqual(result["managed_create_count"], 13)
        self.assertEqual(result["data_change_count"], 1)

    def assert_rejected(self, mutate) -> None:
        candidate = deepcopy(valid_plan())
        mutate(candidate)
        with self.assertRaises(ValueError):
            gate(candidate)

    def test_rejects_unsafe_plan_mutations(self) -> None:
        mutations = [
            lambda value: value["resource_changes"][0]["change"].__setitem__("actions", ["update"]),
            lambda value: value["resource_changes"][0]["change"].__setitem__("actions", ["delete", "create"]),
            lambda value: value["resource_changes"][0]["change"].__setitem__("importing", {"id": "x"}),
            lambda value: value["resource_changes"][0]["change"].__setitem__("importing", {}),
            lambda value: value["resource_changes"].append(
                change("aws_iam_role_policy_attachment.state", "aws_iam_role_policy_attachment", {})
            ),
            lambda value: value["variables"]["state_bucket_name"].__setitem__("value", "other-bucket"),
            lambda value: value["resource_changes"][2]["change"]["after"].__setitem__("force_destroy", True),
            lambda value: value["resource_changes"][0]["change"]["after"].__setitem__(
                "deletion_window_in_days", 7
            ),
            lambda value: value["resource_changes"][4]["change"]["after"].__setitem__(
                "block_public_policy", False
            ),
            lambda value: value["resource_changes"][5]["change"]["after"][
                "versioning_configuration"
            ][0].__setitem__("status", "Suspended"),
            lambda value: value["prior_state"]["values"]["root_module"]["resources"].append(
                {"mode": "managed", "address": "aws_s3_bucket.state"}
            ),
            lambda value: value["prior_state"]["values"]["root_module"].__setitem__(
                "child_modules",
                [{"resources": [{"mode": "managed", "address": "module.x.aws_s3_bucket.state"}]}],
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_rejected(mutate)


class ExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repository = self.base / "repository"
        self.private = self.base / "private"
        self.private.mkdir(mode=0o700)
        terraform_root = self.repository / EXECUTOR.TERRAFORM_ROOT_RELATIVE
        terraform_root.mkdir(parents=True)
        source_root = ROOT / EXECUTOR.TERRAFORM_ROOT_RELATIVE
        for name in EXECUTOR.TERRAFORM_SOURCE_FILES:
            (terraform_root / name).write_bytes((source_root / name).read_bytes())

        self.tfvars = self.private / "state-bootstrap.tfvars"
        self.tfvars.write_text(
            'state_bucket_name = "startup-devops-baseline-state-example-1"\n'
        )
        self.tfvars.chmod(0o600)
        self.request_path = self.private / "request.json"
        self.output = self.private / "attempt-1"
        request = {
            "schemaVersion": "v0.12.1.1-state-bootstrap-plan-request-v1",
            "operation": "plan-state-backend-foundation",
            "repository": "SterlingAureum/startup-devops-baseline",
            "trustedRef": "refs/heads/main",
            "expectedMainCommit": MAIN_SHA,
            "expectedAwsAccountId": ACCOUNT,
            "awsRegion": "us-east-1",
            "terraformRoot": EXECUTOR.TERRAFORM_ROOT_RELATIVE,
            "privateTfvarsPath": str(self.tfvars),
            "privateTfvarsSha256": hashlib.sha256(self.tfvars.read_bytes()).hexdigest(),
            "expectedInputs": {
                "projectName": "startup-devops-baseline",
                "stateBucketName": BUCKET,
                "stateKmsAlias": ALIAS,
                "additionalTags": TAGS,
            },
            "privateOutputDirectory": str(self.output),
            "approval": {
                "notBeforeUtc": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                "expiresAtUtc": (NOW + timedelta(minutes=45)).isoformat().replace("+00:00", "Z"),
            },
            "executionBoundary": {
                "terraformInitBackend": False,
                "terraformPlan": True,
                "terraformShow": True,
                "terraformApply": False,
                "stateMigration": False,
            },
        }
        self.request_path.write_text(json.dumps(request))
        self.request_path.chmod(0o600)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def git_runner(arguments: list[str]) -> str:
        mapping = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): MAIN_SHA,
            ("rev-parse", "origin/main"): MAIN_SHA,
        }
        return mapping[tuple(arguments)]

    def test_verify_is_command_free_and_redacted(self) -> None:
        request, _, _, manifest, remaining = EXECUTOR.verify_inputs(
            self.request_path,
            repository_root=self.repository,
            git_runner=self.git_runner,
            now=NOW,
        )
        result = EXECUTOR.redacted_verification(request, self.request_path, manifest, remaining)
        self.assertEqual(result["commands_executed"], [])
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertNotIn(BUCKET, json.dumps(result))

    def test_execute_runs_plan_only_and_keeps_private_artifacts(self) -> None:
        commands: list[list[str]] = []
        plan_bytes = json.dumps(valid_plan()).encode()

        def runner(
            arguments: list[str],
            environment: dict[str, str],
            timeout: int,
            cwd: Path,
        ) -> subprocess.CompletedProcess[bytes]:
            del environment, timeout, cwd
            commands.append(arguments)
            if arguments[:3] == ["terraform", "version", "-json"]:
                return subprocess.CompletedProcess(arguments, 0, b'{"terraform_version":"1.16.3"}', b"")
            if "get-caller-identity" in arguments:
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    json.dumps({"Account": ACCOUNT, "Arn": "private", "UserId": "private"}).encode(),
                    b"",
                )
            if "plan" in arguments:
                output = next(item.removeprefix("-out=") for item in arguments if item.startswith("-out="))
                Path(output).write_bytes(b"private plan")
                return subprocess.CompletedProcess(arguments, 0, b"planned", b"")
            if "show" in arguments and "-json" in arguments:
                return subprocess.CompletedProcess(arguments, 0, plan_bytes, b"")
            if "show" in arguments and "-no-color" in arguments:
                return subprocess.CompletedProcess(arguments, 0, b"private human plan", b"")
            return subprocess.CompletedProcess(arguments, 0, b"initialized", b"")

        with patch.dict(os.environ, {"CONFIRM_STATE_BOOTSTRAP_PLAN": EXECUTOR.PLAN_CONFIRMATION}, clear=True):
            result = EXECUTOR.execute(
                self.request_path,
                repository_root=self.repository,
                git_runner=self.git_runner,
                runner=runner,
                now=NOW,
            )

        self.assertTrue(any("init" in command and "-backend=false" in command for command in commands))
        self.assertTrue(any("plan" in command for command in commands))
        self.assertFalse(any("apply" in command for command in commands))
        self.assertEqual(result["managed_create_count"], 13)
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertNotIn(BUCKET, json.dumps(result))
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_state_and_permission_drift(self) -> None:
        state = self.repository / EXECUTOR.TERRAFORM_ROOT_RELATIVE / "terraform.tfstate"
        state.write_text("{}")
        with self.assertRaises(ValueError):
            EXECUTOR.verify_inputs(
                self.request_path,
                repository_root=self.repository,
                git_runner=self.git_runner,
                now=NOW,
            )
        state.unlink()
        self.tfvars.chmod(0o644)
        with self.assertRaises(ValueError):
            EXECUTOR.verify_inputs(
                self.request_path,
                repository_root=self.repository,
                git_runner=self.git_runner,
                now=NOW,
            )

    def test_rejects_unsafe_request_mutations(self) -> None:
        value = json.loads(self.request_path.read_text())
        mutations = [
            lambda item: item["executionBoundary"].__setitem__("terraformApply", True),
            lambda item: item["executionBoundary"].__setitem__("stateMigration", True),
            lambda item: item.__setitem__("awsRegion", "us-west-2"),
            lambda item: item["expectedInputs"]["additionalTags"].__setitem__("Environment", "prod"),
            lambda item: item["approval"].__setitem__(
                "expiresAtUtc", (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            ),
        ]
        for mutate in mutations:
            candidate = deepcopy(value)
            mutate(candidate)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                EXECUTOR.validate_request(candidate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
