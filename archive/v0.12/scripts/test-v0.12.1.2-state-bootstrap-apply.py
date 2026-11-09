#!/usr/bin/env python3
"""Offline tests for the v0.12.1.2 reviewed state-bootstrap apply checkpoint."""

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


EXECUTOR = load_module(
    ROOT / "scripts/execute-v0.12.1.2-state-bootstrap-apply.py",
    "state_bootstrap_apply_tests",
)
PLAN_TEST = load_module(
    ROOT / "scripts/test-v0.12.1.1-state-bootstrap-plan.py",
    "state_bootstrap_plan_fixtures",
)

MAIN_SHA = "b" * 40
ACCOUNT = "123456789012"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
BUCKET = PLAN_TEST.BUCKET
ALIAS = PLAN_TEST.ALIAS
TAGS = PLAN_TEST.TAGS


class ApplyExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repository = self.base / "repository"
        self.private = self.base / "private"
        self.private.mkdir(mode=0o700)
        self.terraform_root = self.repository / EXECUTOR.PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE
        self.terraform_root.mkdir(parents=True)
        source_root = ROOT / EXECUTOR.PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE
        for name in EXECUTOR.PLAN_EXECUTOR.TERRAFORM_SOURCE_FILES:
            (self.terraform_root / name).write_bytes((source_root / name).read_bytes())

        self.tfvars = self.private / "state-bootstrap.tfvars"
        self.tfvars.write_text(
            'aws_region = "us-east-1"\n'
            'project_name = "startup-devops-baseline"\n'
            f'state_bucket_name = "{BUCKET}"\n'
            f'state_kms_alias = "{ALIAS}"\n'
            'additional_tags = { Owner = "platform", Repository = "startup-devops-baseline" }\n'
        )
        self.tfvars.chmod(0o600)

        self.bundle = self.private / "plan-bundle"
        self.bundle.mkdir(mode=0o700)
        self.source = self.bundle / "source"
        self.source.mkdir(mode=0o700)
        for name in EXECUTOR.PLAN_EXECUTOR.TERRAFORM_SOURCE_FILES:
            target = self.source / name
            target.write_bytes((self.terraform_root / name).read_bytes())
            target.chmod(0o600)
        (self.bundle / "terraform-data").mkdir(mode=0o700)

        self.plan_request_path = self.private / "plan-request.json"
        self.plan_request = {
            "schemaVersion": "v0.12.1.1-state-bootstrap-plan-request-v1",
            "operation": "plan-state-backend-foundation",
            "repository": "SterlingAureum/startup-devops-baseline",
            "trustedRef": "refs/heads/main",
            "expectedMainCommit": MAIN_SHA,
            "expectedAwsAccountId": ACCOUNT,
            "awsRegion": "us-east-1",
            "terraformRoot": EXECUTOR.PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE,
            "privateTfvarsPath": str(self.tfvars),
            "privateTfvarsSha256": self.digest(self.tfvars),
            "expectedInputs": {
                "projectName": "startup-devops-baseline",
                "stateBucketName": BUCKET,
                "stateKmsAlias": ALIAS,
                "additionalTags": TAGS,
            },
            "privateOutputDirectory": str(self.bundle),
            "approval": {
                "notBeforeUtc": self.utc(NOW - timedelta(minutes=10)),
                "expiresAtUtc": self.utc(NOW + timedelta(minutes=50)),
            },
            "executionBoundary": {
                "terraformInitBackend": False,
                "terraformPlan": True,
                "terraformShow": True,
                "terraformApply": False,
                "stateMigration": False,
            },
        }
        self.write_json(self.plan_request_path, self.plan_request)

        self.plan_document = PLAN_TEST.valid_plan()
        self.plan_json = self.bundle / "terraform-plan.json"
        self.write_json(self.plan_json, self.plan_document)
        self.gate = EXECUTOR.PLAN_GATE.validate(
            self.plan_document,
            expected_bucket_name=BUCKET,
            expected_kms_alias=ALIAS,
            expected_additional_tags=TAGS,
        )
        self.gate_path = self.bundle / "plan-gate.json"
        self.write_json(self.gate_path, self.gate)
        self.plan_text = self.bundle / "terraform-plan.txt"
        self.write_private(self.plan_text, b"reviewed state-bootstrap plan\n")
        self.binary_plan = self.bundle / "state-bootstrap.tfplan"
        self.write_private(self.binary_plan, b"reviewed saved plan")
        self.manifest_path = self.bundle / "source-manifest.json"
        self.write_json(
            self.manifest_path,
            EXECUTOR.PLAN_EXECUTOR.source_manifest(self.source),
        )
        self.version_path = self.bundle / "terraform-version.json"
        self.write_private(self.version_path, b'{"terraform_version":"1.16.3"}')

        self.record_path = self.bundle / "plan-record.json"
        self.record = {
            "schemaVersion": "v0.12.1.1-state-bootstrap-plan-record-v1",
            "status": "state-bootstrap-plan-produced-awaiting-separate-apply-review",
            "controlPlaneCommit": MAIN_SHA,
            "createdAtUtc": self.utc(NOW - timedelta(minutes=5)),
            "expiresAtUtc": self.utc(NOW + timedelta(minutes=45)),
            "privateRequestSha256": self.digest(self.plan_request_path),
            "privateTfvarsSha256": self.digest(self.tfvars),
            "sourceManifestSha256": self.digest(self.manifest_path),
            "binaryPlanSha256": self.digest(self.binary_plan),
            "terraformPlanJsonSha256": self.digest(self.plan_json),
            "terraformPlanTextSha256": self.digest(self.plan_text),
            "planGateSha256": self.digest(self.gate_path),
            "managedCreateCount": 13,
            "dataChangeCount": self.gate["data_change_count"],
            "awsAccountMatched": True,
            "terraformInitBackend": False,
            "terraformPlanExecuted": True,
            "terraformApplyExecuted": False,
            "stateMigrationExecuted": False,
            "backendResourcesCreated": False,
        }
        self.write_json(self.record_path, self.record)

        self.apply_output = self.private / "apply-output"
        self.apply_request_path = self.private / "apply-request.json"
        self.apply_request = self.make_apply_request()
        self.write_json(self.apply_request_path, self.apply_request)
        self.calls: list[list[str]] = []
        self.kms_describe_calls = 0
        self.applied = False

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def utc(value: datetime) -> str:
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write_private(path: Path, content: bytes) -> None:
        path.write_bytes(content)
        path.chmod(0o600)

    def write_json(self, path: Path, value) -> None:
        self.write_private(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())

    def make_apply_request(self) -> dict:
        return {
            "schemaVersion": "v0.12.1.2-state-bootstrap-apply-request-v1",
            "operation": EXECUTOR.APPLY_CONFIRMATION,
            "repository": "SterlingAureum/startup-devops-baseline",
            "trustedRef": "refs/heads/main",
            "expectedMainCommit": MAIN_SHA,
            "expectedAwsAccountId": ACCOUNT,
            "privatePlanRequestPath": str(self.plan_request_path),
            "privatePlanRequestSha256": self.digest(self.plan_request_path),
            "privatePlanBundleDirectory": str(self.bundle),
            "planRecordSha256": self.digest(self.record_path),
            "binaryPlanSha256": self.digest(self.binary_plan),
            "terraformPlanJsonSha256": self.digest(self.plan_json),
            "terraformPlanTextSha256": self.digest(self.plan_text),
            "planGateSha256": self.digest(self.gate_path),
            "sourceManifestSha256": self.digest(self.manifest_path),
            "terraformVersionJsonSha256": self.digest(self.version_path),
            "privateApplyOutputDirectory": str(self.apply_output),
            "approval": {
                "notBeforeUtc": self.utc(NOW - timedelta(minutes=2)),
                "expiresAtUtc": self.utc(NOW + timedelta(minutes=30)),
            },
            "executionBoundary": {
                "terraformApplyExactSavedPlan": True,
                "terraformPlan": False,
                "terraformInit": False,
                "stateMigration": False,
                "iamPolicyAttachment": False,
            },
        }

    @staticmethod
    def git_runner(arguments: list[str]) -> str:
        mapping = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): MAIN_SHA,
            ("rev-parse", "origin/main"): MAIN_SHA,
        }
        return mapping[tuple(arguments)]

    def terraform_outputs(self) -> dict:
        kms_arn = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/example"
        keys = {
            "bootstrap": "bootstrap/terraform.tfstate",
            "runtime-identities": "runtime-identities/terraform.tfstate",
            "dev": "environments/dev/terraform.tfstate",
            "test": "environments/test/terraform.tfstate",
            "prod": "environments/prod/terraform.tfstate",
        }
        policies = {
            root: f"arn:aws:iam::{ACCOUNT}:policy/startup-devops-baseline-terraform-state-{root}"
            for root in keys
        }
        backend = {
            root: {
                "bucket": BUCKET,
                "encrypt": True,
                "key": key,
                "kms_key_id": kms_arn,
                "region": "us-east-1",
                "use_lockfile": True,
            }
            for root, key in keys.items()
        }
        values = {
            "state_bucket_name": BUCKET,
            "state_kms_alias": ALIAS,
            "state_kms_key_arn": kms_arn,
            "root_state_access_policy_arns": policies,
            "state_keys": keys,
            "backend_configuration": backend,
        }
        return {name: {"sensitive": False, "value": value} for name, value in values.items()}

    def runner(self, arguments, environment, timeout, cwd):
        del environment, timeout, cwd
        self.calls.append(arguments)
        if arguments[:3] == ["terraform", "version", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, self.version_path.read_bytes(), b"")
        if arguments[0] == "terraform" and "show" in arguments:
            return subprocess.CompletedProcess(arguments, 0, self.plan_json.read_bytes(), b"")
        if arguments[0] == "terraform" and "apply" in arguments:
            self.applied = True
            state = {
                "version": 4,
                "resources": [{"mode": "managed", "type": "fixture", "instances": [{}]}],
            }
            (self.source / "terraform.tfstate").write_text(json.dumps(state))
            return subprocess.CompletedProcess(arguments, 0, b"Apply complete", b"")
        if arguments[0] == "terraform" and arguments[-2:] == ["state", "list"]:
            content = "\n".join(sorted(EXECUTOR.PLAN_GATE.EXPECTED_MANAGED_ADDRESSES)) + "\n"
            return subprocess.CompletedProcess(arguments, 0, content.encode(), b"")
        if arguments[0] == "terraform" and arguments[-2:] == ["output", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(self.terraform_outputs()).encode(), b"")
        if "get-caller-identity" in arguments:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Account": ACCOUNT}).encode(), b"")
        if "head-bucket" in arguments:
            return subprocess.CompletedProcess(arguments, 254, b"", b"An error occurred (404)")
        if "describe-key" in arguments:
            self.kms_describe_calls += 1
            if self.kms_describe_calls == 1:
                return subprocess.CompletedProcess(arguments, 254, b"", b"NotFoundException")
            value = {
                "KeyMetadata": {
                    "Arn": f"arn:aws:kms:us-east-1:{ACCOUNT}:key/example",
                    "Enabled": True,
                    "KeyState": "Enabled",
                    "KeyManager": "CUSTOMER",
                }
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value).encode(), b"")
        if "list-policies" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b'{"Policies":[]}', b"")
        if "get-bucket-versioning" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b'{"Status":"Enabled"}', b"")
        if "get-public-access-block" in arguments:
            value = {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value).encode(), b"")
        if "get-bucket-ownership-controls" in arguments:
            return subprocess.CompletedProcess(
                arguments, 0,
                b'{"OwnershipControls":{"Rules":[{"ObjectOwnership":"BucketOwnerEnforced"}]}}', b"",
            )
        if "get-bucket-encryption" in arguments:
            value = {"ServerSideEncryptionConfiguration": {"Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "aws:kms",
                    "KMSMasterKeyID": f"arn:aws:kms:us-east-1:{ACCOUNT}:key/example",
                },
                "BucketKeyEnabled": True,
            }]}}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value).encode(), b"")
        if "get-bucket-policy-status" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b'{"PolicyStatus":{"IsPublic":false}}', b"")
        if "get-bucket-policy" in arguments:
            policy = {
                "Statement": [{
                    "Sid": "DenyInsecureTransport",
                    "Effect": "Deny",
                    "Action": "s3:*",
                    "Principal": "*",
                    "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }]
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Policy": json.dumps(policy)}).encode(), b"")
        if "list-object-versions" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b"{}", b"")
        if "get-key-rotation-status" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b'{"KeyRotationEnabled":true}', b"")
        if "get-policy" in arguments:
            arn = arguments[arguments.index("--policy-arn") + 1]
            return subprocess.CompletedProcess(
                arguments, 0,
                json.dumps({"Policy": {"Arn": arn, "AttachmentCount": 0}}).encode(), b"",
            )
        if "list-entities-for-policy" in arguments:
            return subprocess.CompletedProcess(
                arguments, 0,
                b'{"PolicyGroups":[],"PolicyUsers":[],"PolicyRoles":[]}', b"",
            )
        raise AssertionError(f"Unexpected command: {arguments}")

    def verify(self, now=NOW):
        return EXECUTOR.verify_inputs(
            self.apply_request_path,
            repository_root=self.repository,
            git_runner=self.git_runner,
            now=now,
        )

    def execute(self, runner=None, now=NOW):
        with patch.dict(
            os.environ,
            {"CONFIRM_STATE_BOOTSTRAP_APPLY": EXECUTOR.APPLY_CONFIRMATION},
            clear=True,
        ):
            return EXECUTOR.execute(
                self.apply_request_path,
                repository_root=self.repository,
                git_runner=self.git_runner,
                runner=runner or self.runner,
                now=now,
            )

    def test_verify_is_operationally_command_free_and_redacted(self) -> None:
        result = EXECUTOR.redacted_verification(self.verify())
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(self.apply_output.exists())
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertNotIn(BUCKET, json.dumps(result))

    def test_execute_applies_exact_plan_once_and_validates_foundation(self) -> None:
        result = self.execute()
        self.assertTrue(result["terraform_apply_executed"])
        self.assertFalse(result["terraform_plan_executed"])
        self.assertEqual(result["managed_state_address_count"], 13)
        commands = [" ".join(item) for item in self.calls]
        self.assertEqual(sum(" apply " in f" {item} " for item in commands), 1)
        self.assertFalse(any(" plan " in f" {item} " or " destroy " in f" {item} " for item in commands))
        self.assertFalse(any(" init " in f" {item} " for item in commands))
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertNotIn(BUCKET, json.dumps(result))
        for item in self.apply_output.iterdir():
            self.assertEqual(item.stat().st_mode & 0o777, 0o600)

    def test_rejects_artifact_expiry_source_and_state_drift(self) -> None:
        original = self.apply_request["binaryPlanSha256"]
        self.apply_request["binaryPlanSha256"] = "0" * 64
        self.write_json(self.apply_request_path, self.apply_request)
        with self.assertRaises(ValueError):
            self.verify()
        self.apply_request["binaryPlanSha256"] = original
        self.write_json(self.apply_request_path, self.apply_request)
        with self.assertRaises(ValueError):
            self.verify(NOW + timedelta(hours=2))
        (self.terraform_root / "main.tf").write_text("drift")
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.verify()
        (self.terraform_root / "main.tf").write_bytes(
            (ROOT / EXECUTOR.PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE / "main.tf").read_bytes()
        )
        (self.terraform_root / "terraform.tfstate").write_text("{}")
        with self.assertRaisesRegex(ValueError, "local state"):
            self.verify()

    def test_rejects_unsafe_apply_request_mutations(self) -> None:
        mutations = [
            lambda value: value["executionBoundary"].__setitem__("terraformPlan", True),
            lambda value: value["executionBoundary"].__setitem__("stateMigration", True),
            lambda value: value.__setitem__("operation", "terraform-apply"),
            lambda value: value["approval"].__setitem__(
                "expiresAtUtc", self.utc(NOW + timedelta(hours=2))
            ),
        ]
        for mutate in mutations:
            candidate = deepcopy(self.apply_request)
            mutate(candidate)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                EXECUTOR.validate_apply_request(candidate)

    def test_preexisting_resource_stops_before_apply(self) -> None:
        def runner(arguments, environment, timeout, cwd):
            if "head-bucket" in arguments:
                self.calls.append(arguments)
                return subprocess.CompletedProcess(arguments, 0, b"", b"")
            return self.runner(arguments, environment, timeout, cwd)

        with self.assertRaisesRegex(ValueError, "existing resource"):
            self.execute(runner=runner)
        self.assertFalse(self.applied)

    def test_post_apply_failure_preserves_state_without_retry(self) -> None:
        def runner(arguments, environment, timeout, cwd):
            if "get-bucket-versioning" in arguments:
                self.calls.append(arguments)
                return subprocess.CompletedProcess(arguments, 0, b'{"Status":"Suspended"}', b"")
            return self.runner(arguments, environment, timeout, cwd)

        with self.assertRaisesRegex(ValueError, "versioning"):
            self.execute(runner=runner)
        self.assertTrue((self.source / "terraform.tfstate").is_file())
        apply_calls = [item for item in self.calls if item[0] == "terraform" and "apply" in item]
        self.assertEqual(len(apply_calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
