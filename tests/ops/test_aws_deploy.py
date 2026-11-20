import base64
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
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
