import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/ops"))
from aws_cnpg import wait_for_cnpg
from aws_deploy import Cluster
from configuration import OpsError


def cluster_state(ready=False, observed=2):
    return {"metadata": {"generation": 2}, "spec": {"instances": 3}, "status": {
        "readyInstances": 3 if ready else 0, "conditions": [
            {"type": "Ready", "status": "True" if ready else "False", "observedGeneration": observed}]}}


def pod_list():
    return json.dumps({"items": [
        {"metadata": {"name": "db-old-initdb"}, "status": {"phase": "Failed"}},
        {"metadata": {"name": "db-1"}, "status": {"phase": "Running", "containerStatuses": [
            {"name": "postgres", "restartCount": 8, "state": {"waiting": {"reason": "CrashLoopBackOff"}},
             "lastState": {"terminated": {"exitCode": 1}}}]}}]})


class CnpgWaitTests(unittest.TestCase):
    def setUp(self):
        self.g = Cluster("test-context", {}, 10, Path("/test dir/kubeconfig"))
        self.now = 0
        self.clock = self.enter_patch("time.monotonic", side_effect=lambda: self.now)
        self.enter_patch("time.sleep", side_effect=self.advance)

    def enter_patch(self, target, **kwargs):
        mock = patch(target, **kwargs)
        self.addCleanup(mock.stop)
        return mock.start()

    def advance(self, duration):
        self.now += duration

    def test_timeout_includes_container_and_recognized_error_only(self):
        def inspect(*args, **kwargs):
            if "logs" in args:
                self.assertTrue(kwargs["private"])
                self.assertIn("--previous", args)
                return "private text: wait-for-get-cluster dial tcp 172.20.0.1:443: i/o timeout"
            self.assertIn("cnpg.io/cluster=db", args)
            return pod_list()

        with patch.object(self.g, "obj", return_value=cluster_state()), patch.object(self.g, "k", side_effect=inspect), \
                redirect_stdout(io.StringIO()) as progress, self.assertRaises(OpsError) as failure:
            wait_for_cnpg(self.g, "ns", "db")
        text = str(failure.exception)
        self.assertIn("Timed out: Ready=True", text)
        self.assertIn("db-1/postgres: CrashLoopBackOff, restarts=8, lastExit=1", text)
        self.assertIn("Kubernetes API connection to 172.20.0.1:443 timed out", text)
        self.assertIn("--context test-context -n ns logs db-1 -c postgres --previous", text)
        self.assertNotIn("private text", text + progress.getvalue())
        self.assertNotIn("db-old-initdb", text + progress.getvalue())
        self.assertEqual(progress.getvalue().count("CrashLoopBackOff"), 1)

    def test_recovering_instance_can_become_ready(self):
        states = [None, cluster_state(), cluster_state(), cluster_state(True, 1), cluster_state(True)]
        with patch.object(self.g, "obj", side_effect=states) as get, patch.object(self.g, "k", return_value=pod_list()), \
                redirect_stdout(io.StringIO()) as output:
            wait_for_cnpg(self.g, "ns", "db")
        self.assertEqual(get.call_count, 5)
        self.assertIn("creation of ns/", output.getvalue())
        self.assertIn("Ready=True on ns/", output.getvalue())

    def test_missing_cluster_reports_creation_timeout_without_pod_reads(self):
        with patch.object(self.g, "obj", return_value=None), patch.object(self.g, "k") as inspect, \
                redirect_stdout(io.StringIO()), self.assertRaisesRegex(OpsError, "Timed out: creation of"):
            wait_for_cnpg(self.g, "ns", "db")
        inspect.assert_not_called()

    def test_unavailable_diagnostics_preserve_timeout(self):
        for missing in ("pods", "logs"):
            def inspect(*args, **kwargs):
                if missing in args:
                    raise OpsError("diagnostic unavailable")
                return pod_list()
            with self.subTest(missing=missing), patch.object(self.g, "obj", return_value=cluster_state()), \
                    patch.object(self.g, "k", side_effect=inspect), redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(OpsError, "Timed out: Ready=True") as failure:
                wait_for_cnpg(self.g, "ns", "db")
            self.assertIn("Inspect: kubectl", str(failure.exception))
