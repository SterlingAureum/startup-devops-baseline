import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
import aws_eso_bootstrap as eso
from configuration import OpsError


class EsoRaceTests(unittest.TestCase):
    def setUp(self):
        self.g = Mock()
        self.revision = "a" * 40
        self.op = {"phase": "Failed", "startedAt": "old", "syncResult": {"revision": self.revision, "resources": [
            {"kind": "ExternalSecret", "name": "demo-api-postgresql", "status": "SyncFailed", "message":
             'external-secrets-webhook.external-secrets.svc: service "external-secrets-webhook" not found'}]}}
        self.app = {"metadata": {"resourceVersion": "19"}, "spec": {"syncPolicy": {"syncOptions": ["ServerSideApply=true"]}},
                    "status": {"sync": {"revision": self.revision}, "operationState": self.op}}
        self.g.obj.side_effect = lambda ns, resource: self.app if resource == eso.APP else {"kind": "present"}
        self.g.k.return_value = '{"items":[{"endpoints":[{"conditions":{"ready":true},"addresses":["10.0.0.1"]}]}]}'

    def test_same_revision_retry_only_once_when_endpoint_ready(self):
        def wait(description, read):
            self.g.k.return_value = '{"items":[]}'
            self.assertFalse(read())
            self.g.k.return_value = '{"items":[{"endpoints":[{"conditions":{"ready":true},"addresses":["10.0.0.1"]}]}]}'
            self.assertFalse(read())
            self.assertFalse(read())
            patches = [c for c in self.g.k.call_args_list if "patch" in c.args]
            self.assertEqual(len(patches), 1)
            ops = json.loads(patches[0].args[-1])
            self.assertEqual(ops[0]["value"], "19")
            self.assertEqual(ops[1]["value"]["sync"], {"revision": self.revision, "syncOptions": ["ServerSideApply=true"]})
            self.op["phase"] = "Succeeded"
            return read()
        self.g.until.side_effect = wait
        self.assertTrue(eso.wait_for_consumer(self.g))

    def test_foreign_error_revision_and_second_failure_stop(self):
        self.g.until.side_effect = lambda _, read: read()
        self.op["syncResult"]["revision"] = "other"
        with self.assertRaises(OpsError):
            eso.wait_for_consumer(self.g)
        self.g.k.assert_not_called()
        self.op["syncResult"]["revision"] = self.revision
        def twice(_, read):
            read()
            self.op["startedAt"] = "new"
            return read()
        self.g.until.side_effect = twice
        with self.assertRaises(OpsError):
            eso.wait_for_consumer(self.g)
        self.op["syncResult"]["resources"][0]["message"] = "Forbidden"
        self.g.until.side_effect = lambda _, read: read()
        with self.assertRaises(OpsError):
            eso.wait_for_consumer(self.g)
