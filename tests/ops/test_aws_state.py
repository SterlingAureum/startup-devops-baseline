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
from configuration import EXAMPLE_CONFIG, OpsError, environment

ACCOUNT = "123456789012"
TARGET = ("test", "startup-devops-baseline-test", ACCOUNT, "us-east-1")
EMPTY = {"version": 4, "lineage": "080a7801-0ed1-4582-9e9d-9a520a812356",
         "serial": 19, "resources": [], "outputs": {}}


class StateTests(unittest.TestCase):
    def test_fresh_test_entry_previews_then_creates_only_the_selected_infrastructure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            config = folder / "environments.yaml"
            entry = environment(EXAMPLE_CONFIG, "aws-test")
            entry["terraform"]["variables_file"] = "vars.tfvars.json"
            config.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"team": entry}}))
            (folder / "vars.tfvars.json").write_text(json.dumps({
                "public_subnet_cidrs": ["10.20.0.0/24", "10.20.1.0/24"],
                "private_subnet_cidrs": ["10.20.10.0/24", "10.20.11.0/24"],
                "vpc_cidr": "10.20.0.0/16", "eks_service_ipv4_cidr": "172.20.0.0/16",
                "enable_github_actions_runtime_identity": True, "eks_public_access_cidrs": ["192.0.2.1/32"],
                "github_actions_runtime_role_arn": f"arn:aws:iam::{ACCOUNT}:role/{TARGET[1]}-github-runtime-read-role"}))
            backend = folder / "aws-test.tfbackend"
            backend.write_text(f'bucket = "fixture-only"\nkey = "team-a/platform/test.state"\n'
                               f'region = "us-east-1"\nallowed_account_ids = ["{ACCOUNT}"]\n'
                               f'kms_key_id = "arn:aws:kms:us-east-1:{ACCOUNT}:key/test-key"\n'
                               'encrypt = true\nuse_lockfile = true\n')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["preflight", "--env", "team", "--config", str(config), "--check-inputs"]), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report["backend_config_file"], str(backend))
                self.assertEqual(report["state_status"], "not-checked")
            replies = [json.dumps({"Account": ACCOUNT}),
                       json.dumps({"clusters": []}), json.dumps({"Vpcs": []})]
            kubeconfig = folder / "private" / "kubeconfig"
            endpoint = "https://eks.test.invalid"
            live = {"status": "ACTIVE", "endpoint": endpoint, "resourcesVpcConfig": {"vpcId": "vpc-test"}}
            outputs = {"database_mode": "none", "eks_cluster_name": TARGET[1], "environment_name": "test",
                       "eks_cluster_endpoint": endpoint, "vpc_id": "vpc-test"}
            raw = json.dumps({"current-context": TARGET[1], "clusters": [{"cluster": {"server": endpoint}}]})
            def execute(argv, env, private=False):
                if "init" in argv:
                    self.assertTrue(argv[1].endswith("/infra/terraform/aws/environments/test"))
                    self.assertIn("-backend-config=" + str(backend), argv)
                    return ""
                if argv[-2:] == ["state", "pull"]:
                    return ""
                if "output" in argv:
                    return json.dumps({key: {"value": value} for key, value in outputs.items()})
                self.assertEqual(argv[:3], ["aws", "eks", "update-kubeconfig"])
                self.assertIn("--dry-run", argv)
                self.assertEqual(argv[argv.index("--alias") + 1], TARGET[1])
                self.assertEqual(argv[argv.index("--name") + 1], TARGET[1])
                self.assertEqual(env["AWS_PROFILE"], entry["aws"]["profile"])
                return raw
            with patch.object(aws_deploy, "aws_private_path", return_value=kubeconfig), \
                    patch.object(aws_state, "ROOT", folder), patch.object(aws_deploy.Cluster, "aws", side_effect=replies) as aws, \
                    patch.object(aws_deploy, "run", side_effect=execute) as tf, patch.object(aws_deploy, "provision") as plan, \
                    patch.object(aws_deploy, "lifecycle_lock"), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["plan", "--env", "team", "--config", str(config)]), 0)
                self.assertEqual([call.args[:2] for call in aws.call_args_list],
                                 [("sts", "get-caller-identity"), ("eks", "list-clusters"), ("ec2", "describe-vpcs")])
                self.assertIn('"status": "absent"', output.getvalue())
                self.assertEqual([c.args[0][2] for c in tf.call_args_list], ["init", "state"])
                self.assertIsNone(plan.call_args.args[-1])
                command = ["create", "--env", "team", "--config", str(config)]
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command + ["--confirm", "startup-devops-baseline-dev"]), 1)
                self.assertEqual(aws.call_count, len(replies))
                for confirm in (None, TARGET[1]):
                    aws.side_effect = replies + ([json.dumps({"cluster": live})] if confirm else [])
                    tf.reset_mock()
                    self.assertEqual(cli.main(command + (["--confirm", confirm] if confirm else [])), 0)
                    self.assertEqual(tf.call_count, 4 if confirm else 2)
                    self.assertEqual(kubeconfig.exists(), bool(confirm))
                    self.assertEqual(f"Dedicated kubeconfig: {kubeconfig}" in output.getvalue(), bool(confirm))
                    if confirm:
                        self.assertEqual(kubeconfig.read_text(), raw)
                        self.assertEqual(kubeconfig.stat().st_mode & 0o777, 0o600)
                        self.assertIn(aws_deploy.kubectl_hint(kubeconfig, TARGET[1]), output.getvalue())
                    self.assertEqual(plan.call_args.args[3], folder / "vars.tfvars.json")
                    self.assertEqual(plan.call_args.args[-1], confirm)
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["up", "--env", "team", "--config", str(config),
                                               "--confirm", "startup-devops-baseline-dev"]), 1)
                self.assertEqual(plan.call_count, 3)

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

    def test_native_pull_preserves_empty_lineage_and_checks_for_conflicting_infrastructure(self):
        g = Mock(context=TARGET[1])
        with tempfile.TemporaryDirectory() as tmp:
            report = {"environment": "team", "stage": "test", "declared_backend": "s3",
                      "backend_config_file": "test.tfbackend", "terraform_root": tmp,
                      "expected_account_id": ACCOUNT, "region": TARGET[3]}
            for raw, lineage in (("", None), (json.dumps(dict(EMPTY, serial=0, lineage="")), None),
                                 (json.dumps(EMPTY), EMPTY["lineage"])):
                g.aws.side_effect = ['{"clusters":[]}', '{"Vpcs":[]}']
                result = aws_state.check_selected_state(g, report, "plan", pull=lambda: raw)
                self.assertEqual(result.get("lineage"), lineage)
                g.aws.side_effect = [json.dumps({"clusters": [g.context]})]
                with self.assertRaisesRegex(OpsError, "EKS already exists"):
                    aws_state.check_selected_state(g, report, "plan", pull=lambda: raw)
                g.aws.side_effect = ['{"clusters":[]}', '{"Vpcs":[{}]}']
                with self.assertRaisesRegex(OpsError, "VPC already exists"):
                    aws_state.check_selected_state(g, report, "up", pull=lambda: raw)
            with self.assertRaisesRegex(OpsError, "state is absent"):
                aws_state.check_selected_state(g, report, "destroy", pull=lambda: "")

    def test_native_init_and_pull_errors_stop_before_provisioning(self):
        g = Mock(context=TARGET[1], env={})
        env = environment(EXAMPLE_CONFIG, "aws-test")
        report = {"environment": "team", "stage": "test", "declared_backend": "s3",
                  "backend_config_file": "test.tfbackend", "expected_account_id": ACCOUNT, "region": TARGET[3]}
        for replies, error in (([OpsError("backend rejected")], "backend rejected"),
                               (["", OpsError("AccessDenied")], "AccessDenied"),
                               (["", "invalid"], "Invalid JSON")):
            with tempfile.TemporaryDirectory() as tmp, patch.object(aws_deploy, "run", side_effect=replies) as tf, \
                    patch.object(aws_deploy, "provision") as provision, self.assertRaisesRegex(OpsError, error):
                aws_deploy.deploy_stack(g, report, env, Path(tmp) / "inventory", Path(tmp), operation="plan")
            self.assertEqual(tf.call_count, len(replies))
            g.aws.assert_not_called()
            provision.assert_not_called()

    def test_init_preserves_stray_local_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stray = root / "terraform.tfstate"
            stray.write_text(json.dumps(EMPTY))
            run = Mock()
            with self.assertRaisesRegex(OpsError, "Local state exists"):
                aws_state.initialize_backend(run, ["terraform"], {}, root, {"type": "s3"}, root)
            run.assert_not_called()
            self.assertEqual(json.loads(stray.read_text()), EMPTY)

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
