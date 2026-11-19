from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/delivery"))
import common
import flow
import gitops
import image_receipt
import promotion_check
import runtime


class GitOpsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("helm"), "requires Helm")
    def test_effective_helm_precedence_namespace_and_scalar_types(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(common, "ROOT", Path(temp)):
            chart = Path(temp, "chart")
            (chart / "templates").mkdir(parents=True)
            (chart / "Chart.yaml").write_text("apiVersion: v2\nname: fixture\nversion: 1.0.0\n")
            (chart / "templates/result.yaml").write_text(
                "kind: ConfigMap\napiVersion: v1\nmetadata:\n  name: {{ .Release.Name }}\n"
                "  namespace: {{ .Release.Namespace }}\ndata:\n"
                "  result: {{ list .Values.order .Values.name .Values.number .Values.flag "
                "(.Values.missing | default \"absent\") | toJson | squote }}\n")
            (chart / "one.yaml").write_text("order: first\nname: first\n")
            (chart / "two.yaml").write_text("order: last\n")
            app = {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "fixture"},
                   "spec": {"destination": {"server": "https://kubernetes.default.svc", "namespace": "test-ns"},
                            "source": {"path": "chart", "helm": {
                                "valueFiles": ["one.yaml", "two.yaml"], "values": "missing: inline",
                                "valuesObject": {"name": "object", "flag": False},
                                "parameters": [{"name": "number", "value": "10", "forceString": True},
                                               {"name": "flag", "value": "true"}]}}}}
            rendered = yaml.safe_load(gitops.render_chart(app))
            self.assertEqual(rendered["metadata"], {"name": "fixture", "namespace": "test-ns"})
            self.assertEqual(rendered["data"]["result"], '["last","object","10",true,"absent"]')

    @unittest.skipUnless(shutil.which("helm") and shutil.which("kubectl"), "requires Helm and kubectl")
    def test_real_overlay_drift_is_rejected(self):
        cfg = common.config()
        env = cfg["environments"]["aws-test"]
        overlay = common.repo_path(env["root_manifest"]).parent
        docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", str(overlay)], text=True)))
        child = next(x for x in docs if x["metadata"]["name"] == env["application"])
        original = deepcopy(child["spec"])
        real_run = gitops.run
        def execute(cmd, **kwargs):
            if cmd[0] == "kubectl":
                return subprocess.CompletedProcess(cmd, 0, yaml.safe_dump_all(docs))
            return real_run(cmd, **kwargs)
        for change in ("order", "foreign-rev", "inline-source", "parameter-digest", "multi-source"):
            child["spec"] = deepcopy(original)
            src = child["spec"]["source"]
            if change == "order":
                src["helm"]["valueFiles"].reverse()
            elif change == "foreign-rev":
                src["targetRevision"] = "another-branch"
            elif change == "inline-source":
                src["helm"]["valuesObject"] = {"delivery": {"sourceCommit": "b" * 40}}
            elif change == "parameter-digest":
                src["helm"]["parameters"] = [{"name": "image.digest", "value": "sha256:" + "a" * 64}]
            else:
                child["spec"]["sources"] = [src]
            with self.subTest(change=change), patch.object(gitops, "run", side_effect=execute), \
                    patch.dict(os.environ, {"GITHUB_REPOSITORY": "SterlingAureum/startup-devops-baseline"}), \
                    self.assertRaises(common.Rejected):
                gitops.render_environment(cfg, "aws-test")

    def test_dev_fingerprint_scopes_environment_and_shared_inputs(self):
        cfg = common.config()
        with tempfile.TemporaryDirectory() as temp, patch.object(common, "ROOT", Path(temp)), patch.object(flow, "ROOT", Path(temp)):
            def write(name, value="first"):
                path = common.repo_path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            dev = cfg["environments"]["aws-dev"]
            write(dev["values"][0])
            initial = flow.input_fingerprint(cfg, "aws-dev")
            for path in ("clusters/local/platform/values.yaml", "clusters/aws/overlays/test/kustomization.yaml",
                         cfg["environments"]["aws-test"]["values"][0], dev["release"]):
                write(path)
            cfg["environments"]["aws-test"]["url"] = "https://new.example.invalid"
            self.assertEqual(flow.input_fingerprint(cfg, "aws-dev"), initial)
            for path in (dev["values"][0], dev["root_manifest"], "clusters/aws/base/kustomization.yaml",
                         "platform/security/default.yaml", cfg["application"]["chart"] + "/templates/service.yaml"):
                before = flow.input_fingerprint(cfg, "aws-dev")
                write(path, "updated")
                self.assertNotEqual(flow.input_fingerprint(cfg, "aws-dev"), before)

    def test_older_revision_waits_and_descendant_is_terminal(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runtime, "ROOT", Path(temp)):
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=temp, text=True).strip()
            git("init", "-q")
            revisions = []
            for name in ("a", "b"):
                git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", name)
                revisions.append(git("rev-parse", "HEAD"))
            a, b = revisions
            runtime.check_observed_revision(b, b)
            with self.assertRaisesRegex(common.Rejected, "has not reconciled"):
                runtime.check_observed_revision(b, a)
            with self.assertRaises(runtime.Superseded):
                runtime.check_observed_revision(a, b)

    def test_release_file_settings_are_preserved_and_reviewed(self):
        a = {"delivery": {"sourceCommit": "original"}, "image": {"pullPolicy": "Always"}, "retained": True}
        b = deepcopy(a)
        b["delivery"]["sourceCommit"] = "changed"
        self.assertEqual(promotion_check.configuration_fields(a), promotion_check.configuration_fields(b))
        b["image"]["pullPolicy"] = "Never"
        self.assertNotEqual(promotion_check.configuration_fields(a), promotion_check.configuration_fields(b))

    def test_dev_receipt_binds_digest_source_and_original_publish_attempt(self):
        repository = "team/app"
        commit = "a" * 40
        cfg = common.config()
        value = common.release(common.repo_path(cfg["environments"]["aws-dev"]["release"]))
        value["delivery"] = {"sourceCommit": commit, "sourceRepository": repository,
                             "workflowRunId": "123", "workflowRunAttempt": "2"}
        value["image"]["tag"] = value["release"]["applicationVersion"] = "sha-" + commit[:7]
        record = image_receipt.receipt(repository, commit, value["image"]["repository"] + "@" + value["image"]["digest"], "123", "2")
        workflow = {"head_sha": "b" * 40, "id": 123, "run_attempt": 2, "head_branch": "main",
                    "head_repository": {"full_name": repository}, "path": ".github/workflows/delivery-image.yaml",
                    "event": "workflow_run"}
        with patch.object(image_receipt, "api", return_value=workflow), \
                patch.object(image_receipt, "require_source_job") as job, \
                patch.object(image_receipt, "read_artifact", return_value=record) as artifact:
            image_receipt.require_published(repository, value)
            job.assert_called_once_with("repos/team/app/actions/runs/123/attempts/2", "publish", "2", "b" * 40)
            self.assertEqual(artifact.call_args.args[-2:], ("delivery-image-receipt-123-2", "published.json"))
            for key in ("image", "source_commit", "run_attempt"):
                artifact.return_value = dict(record, **{key: "wrong"})
                with self.subTest(key=key), self.assertRaisesRegex(common.Rejected, "receipt differs"):
                    image_receipt.require_published(repository, value)
