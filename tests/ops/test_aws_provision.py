import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_deploy as deploy
import aws_provision as provision
import cli
from configuration import EXAMPLE_CONFIG, OpsError


def change(address, actions, before=None, after=None):
    return {"address": address, "mode": "managed",
            "change": {"actions": actions, "before": before, "after": after}}


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.name = "startup-devops-baseline-dev"
        self.g = Mock(context=self.name)
        self.g.aws.return_value = '{"clusters":[]}'
        self.eks = change("module.eks.aws_eks_cluster.this", ["create"], after={"name": self.name})
        self.plan = {"complete": True, "resource_changes": [self.eks]}

    def test_create_conflict_and_unsafe_plans(self):
        self.g.aws.return_value = json.dumps({"clusters": [self.name]})
        with self.assertRaisesRegex(OpsError, "already exists"):
            provision.check_plan(self.plan, self.g)
        self.eks["change"]["actions"] = ["no-op"]
        self.g.aws.reset_mock()
        provision.check_plan(self.plan, self.g)
        self.g.aws.assert_not_called()
        for actions in (["delete"], ["create", "delete"], ["delete", "create"], ["forget"]):
            with self.subTest(actions=actions), self.assertRaisesRegex(OpsError, "outside create/update"):
                provision.check_plan({"resource_changes": [self.eks, change("module.vpc.example", actions)]}, self.g)
        with self.assertRaisesRegex(OpsError, "incomplete"):
            provision.check_plan(dict(self.plan, complete=False), self.g)
        self.eks["change"]["after"]["name"] = "another-dev"
        with self.assertRaisesRegex(OpsError, "expected EKS"):
            provision.check_plan(self.plan, self.g)

    def test_preview_and_apply_use_exact_generated_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan_path = folder / "generated.tfplan"
            tf = ["terraform", "-chdir=/dev-root"]
            def execute(argv, **kwargs):
                self.assertEqual(kwargs["env"], {"TF_WORKSPACE": "default"})
                self.assertEqual(argv[:2], tf)
                if "show" in argv:
                    return Mock(stdout=json.dumps(self.plan))
                if "plan" in argv:
                    self.assertIn("-out=" + str(plan_path), argv)
                    self.assertIn("-var-file=/private/settings.tfvars", argv)
                    plan_path.write_bytes(b"saved fixture")
                elif "apply" in argv:
                    self.assertEqual(Path(argv[-1]).read_bytes(), b"saved fixture")
                    self.assertNotIn("-auto-approve", argv)
                else:
                    self.fail(argv)
            with patch.object(provision.subprocess, "run", side_effect=execute) as tf_run:
                for confirm in (None, self.name):
                    tf_run.reset_mock()
                    provision.provision(self.g, tf, {"TF_WORKSPACE": "default"}, "/private/settings.tfvars",
                                        plan_path, folder, confirm)
                    actions = [c.args[0][2] for c in tf_run.call_args_list]
                    self.assertEqual(actions, ["plan", "show"] + (["apply"] if confirm else []))
                self.plan["resource_changes"].append(change("module.vpc.aws_vpc.this", ["no-op"], before={"id": "vpc-1"}))
                (folder / "state-lineage.json").write_text('{"vpc":"vpc-1","cleaned":true,"complete":false}')
                with self.assertRaisesRegex(OpsError, "teardown is pending"):
                    provision.provision(self.g, tf, {"TF_WORKSPACE": "default"}, "/private/settings.tfvars",
                                        plan_path, folder, self.name)
                self.assertEqual(tf_run.call_args.args[0][2], "show")

    @unittest.skipUnless(shutil.which("terraform"), "requires Terraform CLI")
    def test_real_saved_plan_create_noop_and_refused_delete(self):
        # Real Terraform and local state. Map only the fixture resource's identity
        # to the EKS shape that the AWS-specific ownership check consumes.
        check = provision.check_plan

        def fixture_identity(plan, cluster):
            for row in plan["resource_changes"]:
                if row["address"] == "terraform_data.cluster":
                    row["address"] = "module.eks.aws_eks_cluster.this"
                    row["change"]["after"]["name"] = row["change"]["after"]["input"]
            return check(plan, cluster)

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "main.tf"
            base = ('variable "cluster" { type = string }\n'
                    'resource "terraform_data" "cluster" { input = var.cluster }\n')
            source.write_text(base + 'resource "terraform_data" "keep" {}\n')
            tf = ["terraform", "-chdir=" + tmp]
            tfenv = dict(os.environ, TF_DATA_DIR=tmp + "/data", TF_WORKSPACE="default")
            variables = folder / "personal.tfvars"
            variables.write_text('cluster = "' + self.name + '"\n')
            subprocess.run(tf + ["init", "-input=false"], env=tfenv, check=True, capture_output=True)
            args = (self.g, tf, tfenv, variables, folder / "create.tfplan", folder)
            with patch.object(provision, "check_plan", side_effect=fixture_identity):
                provision.provision(*args, None)
                self.assertFalse((folder / "terraform.tfstate").exists())
                provision.provision(*args, self.name)
                self.g.aws.reset_mock()
                provision.provision(*args, self.name)
                self.g.aws.assert_not_called()
                source.write_text(base)
                with self.assertRaisesRegex(OpsError, "terraform_data.keep"):
                    provision.provision(*args, self.name)
                state = subprocess.check_output(tf + ["state", "list"], env=tfenv, text=True)
                self.assertEqual(set(state.splitlines()), {"terraform_data.cluster", "terraform_data.keep"})

    def test_real_entry_dispatch_stops_at_selected_phase(self):
        for command, confirm, fails in [("plan", False, False), ("up", False, False), ("create", True, False),
                                        ("up", True, True), ("up", True, False)]:
            with self.subTest(command=command, confirm=confirm, fails=fails), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                report = {"cluster": self.name, "gitops_root": "clusters/aws/overlays/dev/root-app.yaml"}
                outputs = {"environment_name": "dev", "eks_cluster_name": self.name,
                           "eks_cluster_endpoint": "https://eks", "vpc_id": "vpc"}
                events = []
                def run(argv, settings, private=False):
                    if "init" in argv:
                        self.assertTrue(any(a.startswith("-backend-config=") for a in argv))
                        self.assertNotIn("TF_VAR_project_name", settings)
                        events.append("init")
                    elif "output" in argv:
                        events.append("output")
                        return json.dumps({k: {"value": v} for k, v in outputs.items()})
                    elif "update-kubeconfig" in argv:
                        return json.dumps({"current-context": self.name, "clusters": [{"cluster": {"server": "https://eks"}}]})
                    else:
                        self.fail(argv)
                def aws(service, action, *args):
                    if action == "get-caller-identity":
                        return '{"Account":"123456789012"}'
                    self.assertEqual(action, "describe-cluster")
                    return '{"cluster":{"endpoint":"https://eks","status":"ACTIVE","resourcesVpcConfig":{"vpcId":"vpc"}}}'
                def provision_step(g, terraform, settings, variables, plan, receipts, selected):
                    self.assertEqual(selected, self.name if confirm else None)
                    self.assertEqual(settings["TF_WORKSPACE"], "default")
                    events.append("provision")
                    if fails:
                        raise subprocess.CalledProcessError(1, ["terraform", "apply"])
                with patch.dict(deploy.os.environ, {"TF_VAR_project_name": "foreign"}), \
                        patch.object(deploy, "check_selected_state"), patch.object(deploy, "inspect", return_value=report), patch.object(deploy.Cluster, "aws", side_effect=aws), \
                        patch.object(deploy, "lifecycle_lock", return_value=nullcontext(folder)), \
                        patch.object(deploy, "provision", side_effect=provision_step), patch.object(deploy, "run", side_effect=run), \
                        patch.object(deploy, "aws_private_path", return_value=folder / "kubeconfig"), \
                        patch.object(deploy, "kustomize", return_value=[]), patch.object(deploy, "check_deploy_target"), \
                        patch.object(deploy.Cluster, "k"), patch.object(deploy, "prepare"), patch.object(deploy, "gitops"), \
                        patch.object(deploy, "complete"), patch.object(deploy, "check_apps") as healthy, \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = cli.main(["--config", str(EXAMPLE_CONFIG), command, "--env", "aws-dev"] + (["--confirm", self.name] if confirm else []))
                    self.assertEqual(result, 1 if fails else 0)
                    bootstrap = command == "up" and confirm and not fails
                    self.assertEqual(events, ["init", "provision"] + (["output"] if bootstrap else []))
                    self.assertEqual(healthy.called, bootstrap)

    def test_hidden_plan_flags_block_before_init(self):
        env = {"terraform": {"root": "infra/terraform/aws/environments/dev", "variables_file": "dev.tfvars",
                             "backend": {"type": "s3", "config_file": "dev.backend"}}}
        self.g.env = {"TF_CLI_ARGS_plan": "-destroy"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(deploy, "run") as run:
            with self.assertRaisesRegex(OpsError, "TF_CLI_ARGS"):
                deploy.deploy_stack(self.g, {}, env, Path(tmp) / "inventory", Path(tmp), operation="up", confirm=self.name)
            run.assert_not_called()

    def test_invalid_scope_or_confirmation_stops_before_aws(self):
        with patch.object(deploy, "inspect", return_value={"cluster": self.name}), \
                patch.object(deploy.Cluster, "aws") as aws, redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            for args in (["up", "--env", "aws-test"], ["plan", "--env", "local"],
                         ["create", "--env", "aws-dev", "--confirm", "wrong"],
                         ["plan", "--env", "aws-dev", "--confirm", self.name]):
                self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), *args]), 1)
            self.assertEqual(cli.main(["--config", str(EXAMPLE_CONFIG), "up", "--env", "aws-dev", "--dry-run"]), 0)
            aws.assert_not_called()
