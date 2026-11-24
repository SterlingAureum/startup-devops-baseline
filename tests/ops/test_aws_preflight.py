import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
import aws_preflight as aws
import cli
import configuration


class AwsPreflightTests(unittest.TestCase):
    def test_personal_inputs_and_wrong_target_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            env = configuration.environment(configuration.DEFAULT_CONFIG, "aws-dev")
            del env["terraform"]["backend"]  # Existing dev inventories use backend_file.
            env["terraform"].update(variables_file="vars.tfvars.json", backend_file="dev.tfbackend")
            inventory = folder / "environments.yaml"
            inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"aws-dev": env}}))
            account = env["aws"]["expected_account_id"]
            backend = folder / "dev.tfbackend"
            backend.write_text(f'bucket = "fixture-only"\nkey = "environments/dev/terraform.tfstate"\n'
                               f'region = "us-east-1"\nallowed_account_ids = ["{account}"]\n'
                               f'kms_key_id = "arn:aws:kms:us-east-1:{account}:key/test-key"\n'
                               'encrypt = true\nuse_lockfile = true\n')
            command = ["preflight", "--env", "aws-dev", "--config", str(inventory), "--check-inputs"]
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command), 1)
                self.assertIn("Missing input file", error.getvalue())
            values = {"enable_github_actions_runtime_identity": True, "eks_node_desired_size": 4,
                      "github_actions_runtime_role_arn": f"arn:aws:iam::{account}:role/startup-devops-baseline-dev-github-runtime-read-role",
                      "eks_public_access_cidrs": ["192.0.2.4/32"]}
            private = folder / "vars.tfvars.json"
            private.write_text(json.dumps(values))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(command), 0)
                report = json.loads(output.getvalue())
            self.assertEqual((report["scope"], report["live_checks"]), ("personal-files", "pending"))
            self.assertNotIn("192.0.2.4", output.getvalue())
            for key, value in (("environment", "test"), ("aws_region", "us-west-2"),
                               ("eks_public_access_cidrs", ["0.0.0.0/0"]), ("github_actions_runtime_role_arn", "wrong"),
                               ("enable_github_actions_runtime_identity", False)):
                private.write_text(json.dumps({**values, key: value}))
                with self.subTest(key=key), redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command), 1)
            backend.write_text(backend.read_text().replace("environments/dev/", "environments/test/"))
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command), 1)
                self.assertIn("backend key", error.getvalue())

    def test_inventory_aliases_preserve_physical_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            for canonical, alias in (("aws-dev", "sandbox"), ("aws-test", "team-a-test")):
                entry = configuration.environment(configuration.DEFAULT_CONFIG, canonical)
                inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {alias: entry}}))
                for command in ("show", "preflight"):
                    with self.subTest(alias=alias, command=command), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main([command, "--env", canonical]), 0)
                        expected = json.loads(output.getvalue())
                    with redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main([command, "--config", str(inventory), "--env", alias]), 0)
                        self.assertEqual(json.loads(output.getvalue()), {**expected, "environment": alias})
                    self.assertEqual(expected["delivery_environment"], canonical)

    def test_delivery_key_defaults_to_inventory_key_and_validates_before_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(configuration.DEFAULT_CONFIG, "aws-test")
            del entry["delivery_environment"]
            inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"aws-test": entry}}))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["preflight", "--config", str(inventory), "--env", "aws-test"]), 0)
            self.assertEqual(json.loads(output.getvalue())["delivery_environment"], "aws-test")
            for override, message in ((None, "Unknown delivery environment 'team-a-test'"),
                                      ("aws-dev", "must select clusters/aws/overlays/test"),
                                      ("", "delivery_environment must be a nonempty string")):
                if override is not None:
                    entry["delivery_environment"] = override
                inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"team-a-test": entry}}))
                with self.subTest(override=override), redirect_stderr(io.StringIO()) as error, \
                        patch.object(aws.subprocess, "run") as tool:
                    self.assertEqual(cli.main(["preflight", "--config", str(inventory), "--env", "team-a-test"]), 1)
                    self.assertIn(message, error.getvalue())
                    tool.assert_not_called()

    def test_missing_key_and_test_alias_fail_before_external_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(configuration.DEFAULT_CONFIG, "aws-test")
            # Even a dev-looking key cannot enable dev mutations against the test root.
            inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"aws-dev": entry}}))
            with patch.object(aws.subprocess, "run") as tool:
                with redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main(["destroy", "--env", "AWS-dev", "--config", str(inventory)]), 1)
                    self.assertIn("Unknown environment 'AWS-dev'. Available environments: aws-dev", error.getvalue())
                for command in ("create", "up", "deploy", "destroy"):
                    with self.subTest(command=command), redirect_stderr(io.StringIO()):
                        self.assertEqual(cli.main([command, "--env", "aws-dev", "--config", str(inventory)]), 1)
                tool.assert_not_called()

    def test_dev_alias_confirmation_uses_real_cluster(self):
        import aws_deploy
        import aws_destroy

        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(configuration.DEFAULT_CONFIG, "aws-dev")
            inventory.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"sandbox": entry}}))
            for module, command in ((aws_deploy, "up"), (aws_destroy, "destroy")):
                with self.subTest(command=command), redirect_stderr(io.StringIO()) as error, \
                        patch.object(module, "inspect", return_value={"cluster": "actual-dev"}) as inspect, \
                        patch.object(aws.subprocess, "run") as tool:
                    self.assertEqual(cli.main([command, "--env", "sandbox", "--config", str(inventory),
                                               "--confirm", "sandbox"]), 1)
                    selected = inspect.call_args.args[0]
                    self.assertEqual((selected.inventory_name, selected.stage), ("sandbox", "dev"))
                    self.assertIn("--confirm actual-dev", error.getvalue())
                    tool.assert_not_called()

    def test_test_root_supports_local_and_rejects_legacy_s3_file(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["preflight", "--env", "aws-test"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["declared_backend"], "local")
        self.assertTrue(Path(report["state_address"]).is_absolute())
        self.assertEqual(report["state_status"], "not-checked")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(configuration.DEFAULT_CONFIG, "aws-test")
            del entry["terraform"]["backend"]
            entry["terraform"]["backend_file"] = "old-test.tfbackend"
            path.write_text(yaml.safe_dump({"schema_version": 1, "environments": {"aws-test": entry}}))
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(["preflight", "--env", "aws-test", "--config", str(path), "--check-inputs"]), 1)
            self.assertIn("root declares local state", error.getvalue())

    def test_dry_run_and_invalid_env_do_not_start_tools(self):
        with patch.object(aws.subprocess, "run") as tool, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["preflight", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertEqual(cli.main(["preflight", "--env", "unknown"]), 1)
            self.assertEqual(cli.main(["show", "--check-inputs"]), 1)
            tool.assert_not_called()

    def test_lost_rbac_binding_rejected(self):
        with self.assertRaisesRegex(configuration.OpsError, "Missing runtime group permission"):
            aws.check_bindings([], "argocd", "runtime", [("argoproj.io", "applications", "get")])
