"""Regression coverage for the route shared by successful checks and publication."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/delivery"
sys.path.insert(0, str(SCRIPTS))
import check_plan
import flow
from common import config


CFG = config()


def route_outputs(paths):
    outputs = {k: json.dumps(v) for k, v in flow.classify(paths, CFG).items()}
    outputs.update(base="a" * 40, application_id=CFG["application"]["release_name"])
    return outputs


def producer(event="push"):
    return {"GITHUB_EVENT_NAME": event, "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": "b" * 40, "GITHUB_REPOSITORY": "team/app",
            "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "2", "REQUEST_PUBLISH": "false"}


def workflow_run():
    return {"event": "push", "head_sha": "b" * 40, "head_branch": "main", "id": 12,
            "run_attempt": 2, "path": ".github/workflows/delivery-validate.yaml",
            "conclusion": "success", "head_repository": {"full_name": "team/app"}}


class PlanTests(unittest.TestCase):
    def test_runtime_targets_and_promotion_intent(self):
        cases = [
            (["scripts/ops/cli.py"], [], [], False),
            (["scripts/ops/cli.py", CFG["environments"]["aws-test"]["release"]], ["aws-test"], ["aws-test"], False),
            ([CFG["environments"][env]["release"] for env in ("aws-test", "aws-dev")],
             ["aws-dev", "aws-test"], ["aws-dev", "aws-test"], True),
            (["clusters/local/platform/values.yaml"], ["local"], [], False),
            (["clusters/aws/overlays/prod/kustomization.yaml"], ["aws-prod"], [], False),
            (["clusters/local/root-app.yaml", "clusters/aws/overlays/test/root-app.yaml"],
             ["aws-test", "local"], [], False),
            (["clusters/aws/base/platform/demo-api.yaml"], ["aws-dev", "aws-prod", "aws-test"],
             [], False),
            ([CFG["environments"]["aws-dev"]["values"][0]], ["aws-dev"], [], False),
            ([CFG["environments"]["aws-dev"]["release"]], ["aws-dev"], ["aws-dev"], True),
        ]
        for paths, render, runtime, propose in cases:
            with self.subTest(paths=paths):
                plan = check_plan.record(route_outputs(paths), producer())
                self.assertEqual(plan["render_environments"], render)
                self.assertEqual(plan["push_runtime_targets"], runtime)
                self.assertEqual(plan["propose_test_on_verified_dev"], propose)
                self.assertFalse(plan["publish_image"])

    def test_runtime_execution_matrix_and_manual_validation(self):
        self.assertEqual(flow.runtime_matrix(CFG, ["aws-dev", "aws-prod"], False, False),
                         [{"environment": "aws-dev", "stage": "dev"}])
        self.assertEqual(flow.runtime_matrix(CFG, ["aws-prod"], True, True),
                         [{"environment": "aws-prod", "stage": "prod"}])
        for name in ("local", "unknown", "aws-prod"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                flow.runtime_matrix(CFG, [name], True, False)

    def test_new_catalog_target_and_full_manual_checks(self):
        entry = dict(CFG["environments"]["aws-test"], release="releases/team.yaml")
        cfg = dict(CFG, environments=dict(CFG["environments"], team=entry))
        self.assertEqual(flow.classify([entry["release"]], cfg)["runtime_targets"], ["team"])
        self.assertEqual(flow.runtime_matrix(cfg, ["team"], True, False),
                         [{"environment": "team", "stage": "test"}])
        route = flow.classify([], cfg, full_checks=True)
        self.assertEqual(route["environments"], sorted(cfg["environments"]))
        self.assertTrue(all(route[key] for key in ("tests", "iac", "platform", "render")))
        self.assertFalse(route["application"] or route["runtime_targets"])

    def test_manual_and_pr_writes_are_opt_in_and_main_only(self):
        outputs = route_outputs(["apps/demo-api/src/a.py"])
        env = producer("workflow_dispatch")
        self.assertFalse(check_plan.record(outputs, env)["publish_image"])
        env["REQUEST_PUBLISH"] = "true"
        self.assertTrue(check_plan.record(outputs, env)["publish_image"])
        for event, ref in [("pull_request", "refs/pull/1/merge"), ("workflow_dispatch", "refs/heads/test")]:
            with self.subTest(event=event):
                env.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)
                self.assertFalse(check_plan.record(outputs, env)["publish_image"])

    def test_runtime_matrix_preserves_per_target_report_handoff(self):
        workflows = SCRIPTS.parents[1] / ".github/workflows"
        caller = yaml.safe_load((workflows / "delivery-runtime.yaml").read_text())["jobs"]["verify"]
        called = yaml.safe_load((workflows / "delivery-verify.yaml").read_text())["jobs"]
        self.assertFalse(caller["strategy"]["fail-fast"])
        self.assertEqual(caller["with"]["environment"], "${{ matrix.environment }}")
        self.assertEqual(caller["with"]["stage"], "${{ matrix.stage }}")
        self.assertEqual(caller["if"], "needs.route.outputs.matrix != '[]'")
        for row in flow.runtime_matrix(CFG, ["aws-dev", "aws-test"], False, False):
            name = caller["name"].replace("${{ matrix.stage }}", row["stage"])
            child = called["verify"]["name"].replace("${{ inputs.environment }}", row["environment"])
            self.assertEqual(f"{name} / {child}", f"verify-{row['stage']} / verify ({row['environment']})")
        proposal = called["propose-test"]
        self.assertEqual(proposal["needs"], "verify")
        download = next(step for step in proposal["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
        self.assertIn("needs.verify.outputs.report_name", download["with"]["name"])

    def test_consumer_rejects_wrong_producer_or_context(self):
        plan = check_plan.record(route_outputs(["apps/demo-api/Dockerfile"]), producer())
        for field, value in [("id", 13), ("run_attempt", 1), ("event", "pull_request"),
                             ("conclusion", "cancelled"), ("head_sha", "c" * 40),
                             ("head_repository", {"full_name": "fork/app"}), ("path", "other.yaml")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan.publish_intent(plan, dict(workflow_run(), **{field: value}), "team/app")
        for field, value in [("schema_version", 2), ("publish_image", "true"), ("ref", "refs/heads/test")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan.publish_intent(dict(plan, **{field: value}), workflow_run(), "team/app")

    def test_multi_commit_push_survives_serialized_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

            git("init", "-q")
            git("config", "user.email", "test@example.com")
            git("config", "user.name", "Test")
            git("commit", "--allow-empty", "-qm", "base")
            base = git("rev-parse", "HEAD")
            app = root / "apps/demo-api/src/main.py"
            app.parent.mkdir(parents=True)
            app.write_text("print('app')")
            git("add", ".")
            git("commit", "-qm", "app")
            (root / "README.md").write_text("docs")
            git("add", ".")
            git("commit", "-qm", "docs")
            head = git("rev-parse", "HEAD")
            with patch.object(flow, "ROOT", root):
                outputs = route_outputs(flow.changed_paths(base, head))
                self.assertFalse(flow.classify(flow.changed_paths(git("rev-parse", "HEAD^"), head),
                                               CFG)["application"])
            outputs["base"] = base
            plan_file = root / "checked-plan.json"
            output = root / "github-output"
            payload = root / "event.json"
            payload.write_text(json.dumps({"workflow_run": dict(workflow_run(), head_sha=head)}))
            env = dict(os.environ, **producer())
            env.update(GITHUB_SHA=head, RESULTS=json.dumps({"route": {"outputs": outputs}}),
                       GITHUB_EVENT_PATH=str(payload), GITHUB_OUTPUT=str(output),
                       GITHUB_STEP_SUMMARY=str(root / "summary"))
            for action in ("record", "consume"):
                subprocess.run([sys.executable, str(SCRIPTS / "check_plan.py"), action, str(plan_file)],
                               env=env, check=True)
            plan = json.loads(plan_file.read_text())
            self.assertEqual((plan["base"], plan["head"]), (base, head))
            self.assertEqual(output.read_text(), "application=true\n")
