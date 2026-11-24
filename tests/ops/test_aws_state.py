import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_deploy
import aws_state
import cli
from configuration import DEFAULT_CONFIG, OpsError, environment

ACCOUNT = "123456789012"
TARGET = ("test", "startup-devops-baseline-test", ACCOUNT, "us-east-1")
EMPTY = {"version": 4, "lineage": "080a7801-0ed1-4582-9e9d-9a520a812356",
         "serial": 19, "resources": [], "outputs": {}}


class StateTests(unittest.TestCase):
    def test_real_test_entry_resolves_relative_state_and_stops_at_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = folder / "environments.yaml"
            entry = environment(DEFAULT_CONFIG, "aws-test")
            entry["terraform"].update(variables_file="vars.tfvars.json", backend={"type": "local", "path": "data/state"})
            config.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"team": entry}}))
            (folder / "vars.tfvars.json").write_text(json.dumps({
                "enable_github_actions_runtime_identity": True, "eks_public_access_cidrs": ["192.0.2.1/32"],
                "github_actions_runtime_role_arn": f"arn:aws:iam::{ACCOUNT}:role/{TARGET[1]}-github-runtime-read-role"}))
            dest = folder / "data/state"
            def aws(service, action):
                self.assertEqual((service, action), ("sts", "get-caller-identity"))
                return json.dumps({"Account": ACCOUNT})
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["preflight", "--env", "team", "--config", str(config), "--check-inputs"]), 0)
                self.assertEqual(json.loads(output.getvalue())["state_status"], "absent")
            self.assertFalse(dest.parent.exists())
            dest.parent.mkdir()
            dest.write_text(json.dumps(EMPTY))
            with patch.object(aws_deploy.Cluster, "aws", side_effect=aws), patch.object(aws_deploy, "run") as tf, \
                    patch.object(aws_deploy, "provision") as plan, patch.object(aws_deploy, "lifecycle_lock"), \
                    redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["plan", "--env", "team", "--config", str(config)]), 0)
                self.assertIn("-backend-config=path=" + str(dest), tf.call_args.args[0])
                self.assertIn('"serial": 19', output.getvalue())
                self.assertIsNone(plan.call_args.args[-1])
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["up", "--env", "team", "--config", str(config), "--confirm", TARGET[1]]), 1)
                self.assertEqual(plan.call_count, 1)
            self.assertEqual(json.loads(dest.read_text()), EMPTY)

    def test_unreadable_malformed_cache_and_wrong_state_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected"
            for content in ("", "{", '{"version":3,"backend":{}}',
                            json.dumps(dict(EMPTY, outputs={"environment_name": {"value": "dev"}}))):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(OpsError):
                    aws_state.local_snapshot(path, *TARGET)
            with patch.object(Path, "open", side_effect=PermissionError), self.assertRaises(PermissionError):
                aws_state.local_snapshot(path, *TARGET)

    def test_s3_distinguishes_existing_empty_missing_and_denied(self):
        g = Mock(context=TARGET[1])
        report = {"environment": "team", "stage": "test", "state_address": "s3://b/k", "declared_backend": "s3",
                  "terraform_root": "infra/terraform/aws/environments/test", "state_bucket": "b", "backend_file_key": "k", "state_region": "us-east-2",
                  "expected_account_id": ACCOUNT, "region": TARGET[3]}
        def get(*args):
            self.assertEqual(args[:-1], ("s3api", "get-object", "--bucket", "b", "--key", "k", "--region",
                                         "us-east-2", "--expected-bucket-owner", ACCOUNT))
            Path(args[-1]).write_text(json.dumps(EMPTY))
        g.aws.side_effect = get
        with redirect_stdout(io.StringIO()) as out:
            aws_state.check_selected_state(g, report, "plan")
            self.assertIn('"status": "existing"', out.getvalue())
        for code in ("AccessDenied", "NoSuchBucket", "KMS.AccessDeniedException"):
            g.aws.side_effect = OpsError(f"({code}) when calling the GetObject operation")
            with self.subTest(code=code), redirect_stdout(io.StringIO()), self.assertRaisesRegex(OpsError, code):
                aws_state.check_selected_state(g, report, "plan")
        missing = OpsError("(NoSuchKey) when calling the GetObject operation")
        for clusters, vpcs, conflict in (([], [], None), ([g.context], [], "EKS already exists"),
                                         ([], [{"VpcId": "vpc-1"}], "VPC already exists")):
            g.aws.side_effect = [missing, json.dumps({"clusters": clusters}), json.dumps({"Vpcs": vpcs})]
            with redirect_stdout(io.StringIO()):
                if conflict:
                    with self.assertRaisesRegex(OpsError, conflict):
                        aws_state.check_selected_state(g, report, "plan")
                else:
                    aws_state.check_selected_state(g, report, "plan")

    def test_s3_read_error_blocks_dev_before_terraform_init(self):
        g = Mock(context="startup-devops-baseline-dev", env={})
        g.aws.side_effect = OpsError("(AccessDenied) when calling the GetObject operation")
        env = environment(DEFAULT_CONFIG, "aws-dev")
        report = {"environment": "aws-dev", "stage": "dev", "state_address": "s3://b/k", "declared_backend": "s3",
                  "state_bucket": "b", "backend_file_key": "k", "state_region": "us-east-1",
                  "expected_account_id": ACCOUNT, "region": "us-east-1"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(aws_deploy, "run") as terraform, \
                redirect_stdout(io.StringIO()), self.assertRaisesRegex(OpsError, "AccessDenied"):
            aws_deploy.deploy_stack(g, report, env, Path(tmp) / "config", Path(tmp), operation="up", confirm=g.context)
        terraform.assert_not_called()

    def test_absent_selected_file_with_existing_default_stops_before_init(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            folder = Path(tmp)
            (folder / "terraform.tfstate").write_text(json.dumps(EMPTY))
            g = Mock(context=TARGET[1])
            report = {"environment": "team", "stage": "test", "declared_backend": "local",
                      "expected_account_id": ACCOUNT, "region": TARGET[3], "terraform_root": tmp,
                      "state_address": str(folder / "new.tfstate")}
            with self.assertRaisesRegex(OpsError, "terraform.tfstate exists"):
                aws_state.check_selected_state(g, report, "plan")
            g.aws.assert_not_called()

    @unittest.skipUnless(shutil.which("terraform"), "requires Terraform CLI")
    def test_real_terraform_reopens_state_across_working_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config_dir = folder / "inventory"
            config_dir.mkdir()
            settings = {"type": "local", "path": "states/test.tfstate"}
            path = aws_state.backend_path(settings, config_dir)
            for phase in ("first", "reopen"):
                root = folder / phase
                root.mkdir()
                (root / "main.tf").write_text('terraform {\n backend "local" {}\n}\nresource "terraform_data" "sample" {}\n')
                env = dict(os.environ, TF_DATA_DIR=str(root / "data"), TF_WORKSPACE="default")
                def tf(*args):
                    return subprocess.check_output(["terraform", *args], cwd=root, env=env, stderr=subprocess.STDOUT)
                tf("init", "-input=false", "-reconfigure", aws_state.init_argument(settings, config_dir))
                tf("plan", "-input=false", "-out=reviewed")
                if phase == "first":
                    self.assertFalse(path.exists())
                    tf("apply", "-input=false", "reviewed")
                    original = aws_state.local_snapshot(path, *TARGET)
                    self.assertEqual(original["managed_instances"], 1)
                else:
                    self.assertEqual(aws_state.local_snapshot(path, *TARGET), original)
                    changes = json.loads(tf("show", "-json", "reviewed"))["resource_changes"]
                    self.assertEqual(changes[0]["change"]["actions"], ["no-op"])
                self.assertFalse((root / "terraform.tfstate").exists())
