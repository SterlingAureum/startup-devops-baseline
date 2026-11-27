import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_database as db
import aws_deploy as deploy
import aws_destroy as destroy
import aws_retention as retention
from configuration import OpsError


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.account = "123456789012"
        self.region = "us-east-1"
        self.aws = {"expected_account_id": self.account, "region": self.region}
        self.g = Mock(context="sample-dev", env={"AWS_REGION": self.region})
        self.name = self.g.context + "/demo-api/postgresql"
        self.bucket = "sample-dev-123456789012-us-east-1-cnpg"
        self.arn = f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:{self.name}-abcdef"
        self.secret = {"Name": self.name, "ARN": self.arn}
        self.missing = OpsError("(NoSuchBucket) when calling the GetBucketTagging operation")
        self.summary = {"database_storage": list(db.DURABLE), "database_secret_arn": self.arn}
        self.resources = []
        for address in sorted(db.DURABLE):
            module, typ, name = address.rsplit(".", 2)
            attrs = {"id": self.bucket, "bucket": self.bucket, "force_destroy": True,
                     "name": self.name, "arn": self.arn}
            self.resources.append({"mode": "managed", "module": module, "type": typ, "name": name,
                                   "instances": [{"attributes": attrs}]})

    def test_live_dev_rebuild_and_destroy_preview_share_exact_aws_status(self):
        state = {"resources": self.resources}
        for migrated in (False, True):
            if migrated:
                for r in self.resources:
                    a = ".".join((r["module"], r["type"], r["name"]))
                    r["module"] = db.DEV_MOVES[a].rsplit(".", 2)[0]
            targets, keep = destroy.partition(state)
            self.g.aws.side_effect = [self.missing, json.dumps(self.secret)] * 2
            with redirect_stdout(io.StringIO()) as output:
                missing = retention.report_storage(self.g, self.aws, state, targets, keep, None, False)
                result = retention.live_dev_storage(self.g, self.aws, self.summary)
            self.assertEqual({db.original(a) for a in missing}, db.DURABLE - {db.SECRET})
            self.assertEqual(result["database_storage"], [db.SECRET])
            self.assertIn("-var=retained_database_bucket=false", db.dev_variables("dev", "none", result))
            self.assertIn("-var=retained_database_secret=true", db.dev_variables("dev", "none", result))
            self.assertIn("Stale state addresses: 7", output.getvalue())
            self.assertIn(self.name + " (creation marker missing in state)", output.getvalue())

    def test_untagged_bucket_denial_pending_secret_and_replaced_identity(self):
        self.g.aws.side_effect = OpsError("(NoSuchTagSet) when calling the GetBucketTagging operation")
        self.assertEqual(retention.observe(self.g, db.BUCKET, self.account, self.region).status, "present")
        self.g.aws.side_effect = OpsError("(AccessDenied) when calling the GetBucketTagging operation")
        with self.assertRaisesRegex(OpsError, "AccessDenied"):
            retention.live_dev_storage(self.g, self.aws, self.summary)
        self.g.aws.side_effect = [self.missing, json.dumps(dict(self.secret, DeletedDate="2026-12-01"))]
        with self.assertRaisesRegex(OpsError, "scheduled for deletion"):
            retention.live_dev_storage(self.g, self.aws, self.summary)
        replacement = self.secret.copy()
        replacement["ARN"] = self.arn.removesuffix("abcdef") + "uvwxyz"
        self.g.aws.side_effect = [self.missing, json.dumps(replacement)]
        with self.assertRaisesRegex(OpsError, "identity differs"):
            retention.live_dev_storage(self.g, self.aws, self.summary)
        self.g.aws.reset_mock()
        with self.assertRaisesRegex(OpsError, "identity differs"):
            retention.observe(self.g, db.SECRET, self.account, self.region, expected_arn=self.arn.replace(self.region, "us-west-2"))
        self.g.aws.assert_not_called()

    def test_dev_none_plan_uses_live_storage_at_provision_entry(self):
        env = {"terraform": {"root": "infra/terraform/aws/environments/dev", "variables_file": "dev.tfvars",
               "backend": {"type": "s3", "config_file": "dev.tfbackend"}}}
        report = dict(self.aws, stage="dev", database_mode="none")
        self.g.aws.side_effect = [self.missing, json.dumps(self.secret)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(deploy, "check_selected_state", return_value=self.summary), \
                patch.object(deploy, "run") as run, patch.object(deploy, "provision") as provision:
            deploy.deploy_stack(self.g, report, env, Path(tmp) / "inventory", Path(tmp), operation="plan")
        self.assertIn("init", run.call_args.args[0])
        self.assertEqual(provision.call_args.kwargs["implicit"], ["-var=database_mode=none",
                         "-var=retained_database_bucket=false", "-var=retained_database_secret=true"])

    def test_test_preview_explains_live_unmarked_data_without_refresh_or_apply(self):
        self.g.context = "sample-test"
        for row in self.resources:
            attrs = row["instances"][0]["attributes"]
            for key in ("id", "bucket", "name", "arn"):
                attrs[key] = attrs[key].replace("sample-dev", self.g.context)
        state = {"resources": self.resources, "serial": 35, "lineage": "1" * 36}
        env = {"aws": self.aws, "terraform": {"root": "infra/terraform/aws/environments/test",
               "backend": {"type": "s3", "config_file": "test.tfbackend"}}}
        secret = {k: v.replace("sample-dev", self.g.context) for k, v in self.secret.items()}
        self.g.aws.side_effect = ['{"clusters":[]}', '{"TagSet":[]}', json.dumps(secret)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(destroy, "run", side_effect=["", json.dumps(state)]) as tf, \
                patch.object(destroy.subprocess, "run") as apply, redirect_stdout(io.StringIO()) as output:
            destroy.session(self.g, env, Path(tmp) / "inventory", None, Path(tmp), tmp)
            self.assertEqual([c.args[0][2] for c in tf.call_args_list], ["init", "state"])
            apply.assert_not_called()
        self.assertEqual(output.getvalue().count("creation marker missing in state"), 2)
        self.assertIn("No AWS deletion targets for sample-test", output.getvalue())
        self.assertNotIn("Stale Terraform addresses", output.getvalue())

    def test_confirmed_state_only_refresh_requires_exact_verified_drift(self):
        missing = db.DURABLE - {db.SECRET}
        drift = [{"mode": "managed", "address": a, "change": {"actions": ["delete"]}} for a in missing]
        plan = {"resource_drift": drift}
        state = {"resources": [r for r in self.resources if r["type"] == "aws_secretsmanager_secret"]}
        with tempfile.TemporaryDirectory() as tmp:
            def refresh(confirm):
                destroy.refresh_missing(tf, ["terraform"], {}, tmp, {"variables_file": "dev.tfvars"},
                                        Path(tmp), "dev", "cnpg", missing, db.DURABLE, confirm, self.g.context, ("dev", 85))
            tf = Mock(side_effect=["", json.dumps(plan), '{"lineage":"dev","serial":85}', json.dumps(state)])
            with patch.object(destroy.subprocess, "run") as apply:
                refresh(None)
                tf.assert_not_called()
                refresh(self.g.context)
                apply.assert_called_once()
                args = tf.call_args_list[0].args
                self.assertIn("-refresh-only", args)
                self.assertEqual({a[8:] for a in args if a.startswith("-target=")}, missing)
                for unsafe in (drift[:-1], drift + [{"mode": "managed", "address": db.SECRET, "change": {"actions": ["delete"]}}]):
                    tf.side_effect = ["", json.dumps({"resource_drift": unsafe})]
                    with self.assertRaisesRegex(OpsError, "verified missing"):
                        refresh(self.g.context)
                tf.side_effect = ["", json.dumps(plan), '{"lineage":"dev","serial":86}']
                with self.assertRaisesRegex(OpsError, "state changed"):
                    refresh(self.g.context)
                apply.assert_called_once()

    def test_deletion_outcome_reports_scheduled_date_and_rechecks_incomplete_delete(self):
        pending = {"pending_data_deletions": {db.SECRET: self.arn}}
        self.g.aws.side_effect = [json.dumps(self.secret), json.dumps(dict(self.secret, DeletedDate="2026-12-01"))]
        with self.assertRaisesRegex(OpsError, "still exists"):
            destroy.verify_deleted_storage(self.g, self.aws, pending)
        with redirect_stdout(io.StringIO()) as output:
            destroy.verify_deleted_storage(self.g, self.aws, pending)
        self.assertIn("scheduled for deletion", output.getvalue())
        self.assertIn("2026-12-01", output.getvalue())

    def test_archive_source_uses_installed_store_and_snapshot_receipt_survives_retry(self):
        destination = f"s3://{self.bucket}/postgresql-baseline/actual-generation"
        cluster = {"metadata": {"name": "postgresql-baseline"}, "spec": {"plugins": [
            {"name": "barman-cloud.cloudnative-pg.io", "parameters": {"barmanObjectName": "store", "serverName": "db"}}]}}
        self.g.obj.side_effect = [{"kind": "CRD"}, cluster, {"kind": "CRD"},
                                  {"spec": {"configuration": {"destinationPath": destination}}}] * 2
        journal = {"snapshots": {}}
        save = Mock()
        for _ in range(2):
            destroy.record_archive(self.g, {"cnpg_backup_bucket_name": self.bucket}, journal, save)
        save.assert_called_once()
        self.assertEqual(journal["cnpg_archives"][0]["destination"], destination)
        self.assertEqual(journal["cnpg_archives"][0]["server_name"], "db")
        self.g.aws.side_effect = ['{"SnapshotId":"snap-01"}']
        destroy.backup(self.g, {"vol-01": "observability/prometheus"}, journal, save)
        destroy.reopen_receipt(journal)
        self.assertEqual(journal["snapshot_sources"]["snap-01"]["claim"], "observability/prometheus")
        self.assertEqual(journal["snapshot_sources"]["snap-01"]["volume"], "vol-01")
        self.assertEqual(journal["prior_snapshots"], ["snap-01"])
