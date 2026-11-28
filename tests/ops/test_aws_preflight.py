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
from configuration import EXAMPLE_CONFIG
import configuration


class AwsPreflightTests(unittest.TestCase):
    def test_personal_inputs_and_wrong_target_from_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            env = configuration.environment(EXAMPLE_CONFIG, "aws-dev")
            env["database"] = {"mode": "cnpg"}
            env["terraform"]["variables_file"] = "vars.tfvars.json"
            env["terraform"]["backend"] = {"type": "s3", "config_file": "dev.tfbackend"}
            inventory = folder / "environments.yaml"
            inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"aws-dev": env}}))
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
            for key, override, policy in (
                    ("eks_service_ipv4_cidr", "172.21.0.0/16", "allow-cnpg-to-kubernetes-api"),
                    ("private_subnet_cidrs", ["10.30.10.0/24", "10.30.11.0/24"], "allow-cnpg-to-kubernetes-api"),
                    ("public_subnet_cidrs", ["10.30.0.0/24", "10.30.1.0/24"], "allow-alb-to-demo-api")):
                private.write_text(json.dumps({**values, key: override}))
                with self.subTest(policy=policy, key=key), redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main(command), 1)
                    self.assertIn(policy, error.getvalue())
                    self.assertIn("Terraform expects", error.getvalue())
                    self.assertIn("renders", error.getvalue())
            private.write_text(json.dumps(values))
            backend.write_text('assume_role = { role_arn = "arn:aws:iam::123456789012:role/state" }')
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(command), 0)
            backend.unlink()
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(command), 1)
                self.assertIn(str(backend), error.getvalue())

    def test_inventory_aliases_preserve_physical_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            for canonical, alias in (("aws-dev", "sandbox"), ("aws-test", "team-a-test")):
                entry = configuration.environment(EXAMPLE_CONFIG, canonical)
                inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {alias: entry, canonical: entry}}))
                for command in ("show", "preflight"):
                    with self.subTest(alias=alias, command=command), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main(["--config", str(inventory), command, "--env", canonical]), 0)
                        expected = json.loads(output.getvalue())
                    with redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main([command, "--config", str(inventory), "--env", alias]), 0)
                        self.assertEqual(json.loads(output.getvalue()), {**expected, "environment": alias})
                    self.assertEqual(expected["delivery_environment"], canonical)

    def test_show_aws_paths_use_personal_inputs_and_physical_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            file = folder / "inventory.yaml"
            entry = configuration.environment(EXAMPLE_CONFIG, "aws-test")
            entry["terraform"]["variables_file"] = "test.tfvars.json"
            entry["terraform"]["backend"] = {"type": "s3", "config_file": "inputs/test.tfbackend"}
            file.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"team": entry}}))
            def paths():
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(cli.main(["show", "--config", str(file), "--env", "team"]), 0)
                return json.loads(out.getvalue())["paths"]
            self.assertIsNone(paths()["kubeconfig"])
            var_file = folder / "test.tfvars.json"
            var_file.write_text('{"project_name": "sandbox"}')
            with patch.object(aws.subprocess, "run") as run:
                selected = paths()
                run.assert_not_called()
            self.assertEqual(selected["variables_file"], str(var_file))
            self.assertEqual(selected["backend_config_file"], str(folder / "inputs/test.tfbackend"))
            self.assertEqual(selected["kubeconfig"], str(Path.home() /
                ".kube/startup-devops-baseline/aws/123456789012/us-east-1/sandbox-test.yaml"))
            self.assertFalse((folder / "inputs").exists())

    def test_delivery_key_is_explicit_and_validated_before_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(EXAMPLE_CONFIG, "aws-test")
            del entry["delivery_environment"]
            for override, message in ((None, "delivery_environment must be a nonempty string"),
                                      ("missing", "Unknown delivery environment 'missing'"),
                                      ("aws-dev", "must select clusters/aws/profiles/test-no-database"),
                                      ("", "delivery_environment must be a nonempty string")):
                if override is not None:
                    entry["delivery_environment"] = override
                inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"team-a-test": entry}}))
                with self.subTest(override=override), redirect_stderr(io.StringIO()) as error, \
                        patch.object(aws.subprocess, "run") as tool:
                    self.assertEqual(cli.main(["preflight", "--config", str(inventory), "--env", "team-a-test"]), 1)
                    self.assertIn(message, error.getvalue())
                    tool.assert_not_called()

    def test_missing_key_fails_and_alias_selects_physical_test_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(EXAMPLE_CONFIG, "aws-test")
            # An inventory alias can have a different name from its physical target.
            inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"aws-dev": entry}}))
            with patch.object(aws.subprocess, "run") as tool:
                with redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main(["destroy", "--env", "AWS-dev", "--config", str(inventory)]), 1)
                    self.assertIn("Unknown environment 'AWS-dev'. Available environments: aws-dev", error.getvalue())
                for command in ("up", "deploy"):
                    with self.subTest(command=command), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main([command, "--env", "aws-dev", "--config", str(inventory), "--dry-run"]), 0)
                        self.assertEqual(json.loads(output.getvalue())["gitops_root"],
                                         "clusters/aws/profiles/test-no-database/root-app.yaml")
                tool.assert_not_called()

    def test_dev_alias_confirmation_uses_real_cluster(self):
        import aws_deploy
        import aws_destroy

        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "inventory.yaml"
            entry = configuration.environment(EXAMPLE_CONFIG, "aws-dev")
            inventory.write_text(yaml.safe_dump({"schema_version": 2, "environments": {"sandbox": entry}}))
            for module, command, entrypoint, result in (
                    (aws_deploy, "up", "inspect", {"cluster": "actual-dev"}),
                    (aws_destroy, "destroy", "inspect_infrastructure", ({"cluster": "actual-dev"}, {}))):
                with self.subTest(command=command), redirect_stderr(io.StringIO()) as error, \
                        patch.object(module, entrypoint, return_value=result) as inspect, \
                        patch.object(aws.subprocess, "run") as tool:
                    self.assertEqual(cli.main([command, "--env", "sandbox", "--config", str(inventory),
                                               "--confirm", "sandbox"]), 1)
                    selected = inspect.call_args.args[0]
                    self.assertEqual((selected.inventory_name, selected.stage), ("sandbox", "dev"))
                    self.assertIn("--confirm actual-dev", error.getvalue())
                    tool.assert_not_called()

    def test_default_local_state_paths(self):
        for stage in ("dev", "test"):
            name = "aws-" + stage
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "preflight", "--env", name]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["declared_backend"], "local")
            self.assertEqual(Path(report["state_address"]), Path.home() / ".local/state/startup-devops-baseline"
                             / name / "terraform.tfstate")

    def test_dry_run_and_invalid_env_do_not_start_tools(self):
        with patch.object(aws.subprocess, "run") as tool, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "preflight", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "preflight", "--env", "unknown"]), 1)
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "show", "--check-inputs"]), 1)
            tool.assert_not_called()

    def test_lost_rbac_binding_rejected(self):
        with self.assertRaisesRegex(configuration.OpsError, "Missing runtime group permission"):
            aws.check_bindings([], "argocd", "runtime", [("argoproj.io", "applications", "get")])
