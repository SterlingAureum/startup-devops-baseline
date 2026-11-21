import base64
import io
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_deploy as deploy
import aws_standard_demo as demo
import cli
from configuration import OpsError


class AwsDeployTests(unittest.TestCase):
    def test_deploy_dry_run_does_not_contact_cloud(self):
        with patch.object(deploy, "deploy") as invoke, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["deploy", "--env", "aws-dev", "--dry-run"]), 0)
            self.assertIn("refresh dedicated kubeconfig", json.loads(output.getvalue())["steps"])
            invoke.assert_not_called()

    def test_wait_on_older_client_and_fail_on_forbidden(self):
        cluster = deploy.Cluster("example", {}, 60)
        with patch.object(cluster, "k", side_effect=["", '{"kind":"Secret"}']) as k, patch("time.sleep"):
            self.assertEqual(cluster.exists("data-platform", "secret/db")["kind"], "Secret")
            self.assertIn("--ignore-not-found", k.call_args.args)
        with patch.object(cluster, "k", side_effect=OpsError("Forbidden")):
            with self.assertRaisesRegex(OpsError, "Forbidden"):
                cluster.exists("data-platform", "secret/db")

    def test_existing_and_first_secret_versions(self):
        for stages in ({}, {"existing": ["AWSCURRENT"]}):
            with self.subTest(stages=stages):
                g = Mock()
                g.exists.side_effect = [
                    {"data": {"fqdn-uri": base64.b64encode(b"postgresql://fixture").decode()},
                     "metadata": {"uid": "fixture-uid"}},
                    {"spec": {"data": [{"remoteRef": {"property": "DATABASE_URL", "key": "demo"}}]}},
                    {"data": {"DATABASE_URL": "encoded"}},
                ]
                g.aws.return_value = json.dumps({"VersionIdsToStages": stages, "Name": "demo"})
                demo.seed_database(g, {"external_secrets_secret_name": "demo", "external_secrets_secret_arn": "arn"})
                calls = g.aws.call_args_list
                self.assertEqual(len(calls), 1 if stages else 3)
                if not stages:
                    self.assertTrue(calls[1].kwargs["private"])
                    self.assertNotIn("postgresql://fixture", calls[1].args)
                    self.assertNotIn("--remove-from-version-id", calls[2].args)

    def test_dns_existing_foreign_alias_is_preserved(self):
        g = Mock()
        g.until.return_value = "dev.elb.amazonaws.com"
        g.aws.side_effect = [
            json.dumps({"LoadBalancers": [{"DNSName": g.until.return_value, "VpcId": "v", "Type": "application",
                                            "CanonicalHostedZoneId": "alb-zone"}]}),
            json.dumps({"ResourceRecordSets": [{"Name": "demo.example.", "Type": "A", "ResourceRecords": []}]}),
        ]
        with self.assertRaisesRegex(OpsError, "points elsewhere"):
            demo.reconcile_dns(g, {"demo_api_hostname": "demo.example", "vpc_id": "v", "route53_hosted_zone_id": "zone"})
        self.assertEqual(g.aws.call_count, 2)

    def test_deploy_entry_rebuild_and_blocked_redeploy(self):
        report = {"cluster": "startup-devops-baseline-dev", "gitops_root": "clusters/aws/overlays/dev/root-app.yaml"}
        name = report["cluster"]
        out = {"environment_name": "dev", "eks_cluster_name": name, "eks_cluster_endpoint": "https://eks",
               "vpc_id": "vpc-1"}
        def aws(*args):
            if args[:2] == ("sts", "get-caller-identity"):
                return '{"Account":"123456789012"}'
            return '{"cluster":{"status":"ACTIVE","endpoint":"https://eks","resourcesVpcConfig":{"vpcId":"vpc-1"}}}'

        def run(args, env, private=False):
            if args[0] == "aws":
                return json.dumps({"current-context": name, "clusters": [{"cluster": {"server": "https://eks"}}]})
            if "output" in args:
                return json.dumps({key: {"value": value} for key, value in out.items()})
            if "init" in args:
                return ""
            self.fail("Unexpected command: " + str(args))

        for scenario in ("fresh", "deleting namespace", "deleting root"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                if scenario != "fresh":
                    (folder / "prior.json").write_text("preserve checkpoint")

                def kubectl(*args):
                    if "namespaces" in args:
                        target = "startup-apps" if scenario == "deleting namespace" else "unrelated"
                        return json.dumps({"items": [{"metadata": {"name": target, "deletionTimestamp": "now"}}]})
                    if "crd/applications.argoproj.io" in args:
                        return '{"kind":"CustomResourceDefinition"}' if scenario == "deleting root" else ""
                    if "applications.argoproj.io/startup-devops-aws-dev-root" in args:
                        return '{"metadata":{"deletionTimestamp":"now"}}'
                    if "nodes" in args:
                        return ""
                    self.fail("Unexpected kubectl arguments: " + str(args))

                with patch.object(deploy, "inspect", return_value=report), \
                        patch.object(deploy, "lifecycle_lock", return_value=nullcontext(folder)), \
                        patch.object(deploy, "private_path", return_value=folder / "kubeconfig"), \
                        patch.object(deploy, "run", side_effect=run), \
                        patch.object(deploy.Cluster, "aws", side_effect=aws), \
                        patch.object(deploy.Cluster, "k", side_effect=kubectl), \
                        patch.object(deploy, "prepare") as prepare, patch.object(deploy, "gitops") as gitops, \
                        patch.object(demo, "seed_database") as seed, patch.object(demo, "reconcile_dns") as dns, \
                        patch.object(deploy, "check_apps") as verify, redirect_stdout(io.StringIO()), \
                        redirect_stderr(io.StringIO()) as errors:
                    result = cli.main(["deploy", "--env", "aws-dev"])
                    if scenario == "fresh":
                        self.assertEqual(result, 0)
                        seed.assert_called_once()
                        dns.assert_called_once()
                        verify.assert_called_once()
                    else:
                        self.assertEqual(result, 1)
                        self.assertIn("Deploy blocked by deletion", errors.getvalue())
                        prepare.assert_not_called()
                        gitops.assert_not_called()
                        seed.assert_not_called()
                        self.assertEqual((folder / "prior.json").read_text(), "preserve checkpoint")
