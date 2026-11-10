"""Regression coverage for Argo API omission of empty HelmParameter fields."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ops"))
sys.path.insert(0, str(ROOT / "scripts/examples"))
import cli
import configuration
import demo_api
import local

COMMIT = "b" * 40


def api_roundtrip(application):
    result = deepcopy(application)
    for item in result["spec"]["source"].get("helm", {}).get("parameters", []):
        if item.get("value") == "":
            item.pop("value", None)
        if item.get("forceString") is False:
            item.pop("forceString", None)
    return result


def old_root():
    return demo_api.root_application(demo_api.parser().parse_args(["deploy", "--revision", COMMIT]), COMMIT)


def healthy(application):
    result = api_roundtrip(application)
    result["status"] = {"sync": {"status": "Synced", "revision": result["spec"]["source"]["targetRevision"]},
                        "health": {"status": "Healthy"}}
    return result


class HelmParameterTests(unittest.TestCase):
    def test_api_omitted_empty_value_and_false_force_string_are_equivalent(self):
        desired = old_root()
        desired["spec"]["source"]["helm"]["parameters"] = [
            {"name": "image.digest", "value": "", "forceString": True},
            {"name": "replicas", "value": "1", "forceString": False}]
        actual = healthy(desired)
        before = deepcopy(actual)
        local.application_ready(actual, desired)
        self.assertEqual(actual, before)

    def test_actual_value_or_force_string_change_still_fails(self):
        desired = old_root()
        desired["spec"]["source"]["helm"]["parameters"] = [
            {"name": "image.digest", "value": "", "forceString": True}]
        for field, changed in (("value", "different-digest"), ("forceString", False)):
            actual = healthy(desired)
            actual["spec"]["source"]["helm"]["parameters"][0][field] = changed
            with self.subTest(field=field), self.assertRaises(configuration.OpsError):
                local.application_ready(actual, desired)

    def test_invalid_parameter_types_have_explicit_errors(self):
        for parameter in ({"value": ""}, {"name": "image.digest", "value": None},
                          {"name": "setting", "value": False}, {"name": "setting", "value": 1},
                          {"name": "setting", "forceString": "false"}):
            with self.subTest(parameter=parameter), self.assertRaises(configuration.OpsError):
                local.helm_parameters([parameter])

    def test_only_parameters_are_normalized(self):
        desired = old_root()
        actual = healthy(desired)
        actual["spec"]["source"]["helm"]["releaseName"] = "another-release"
        with self.assertRaises(configuration.OpsError):
            local.application_ready(actual, desired)

    @unittest.skipUnless(shutil.which("helm"), "Helm required for actual rendering")
    def test_live_root_without_empty_value_renders_and_clears_cloud_digest(self):
        root = api_roundtrip(old_root())
        before = deepcopy(root)
        self.assertTrue(any("value" not in item for item in root["spec"]["source"]["helm"]["parameters"]))
        with redirect_stdout(io.StringIO()):
            children = local.render_children(root, ROOT)
        child = next(item for item in children if item["metadata"]["name"] == "demo-api")
        params = {item["name"]: item["value"] for item in child["spec"]["source"]["helm"]["parameters"]}
        self.assertEqual(params["image.digest"], "")
        self.assertEqual(params["image.tag"], "local-" + COMMIT[:12])
        self.assertEqual(root, before)

    @unittest.skipUnless(shutil.which("helm"), "Helm required for actual rendering")
    def test_existing_deployment_cli_verify_handles_root_and_children_api_roundtrip(self):
        root = old_root()
        with redirect_stdout(io.StringIO()):
            children = local.render_children(root, ROOT)
        live = {item["metadata"]["name"]: healthy(item) for item in [root, *children]}
        commands = []
        def read(*command):
            commands.append(command)
            output = ""
            if "application" in command:
                name = command[command.index("application") + 1]
                output = json.dumps(live[name])
            return subprocess.CompletedProcess([], 0, output, "")
        with patch.object(cli.shutil, "which", return_value="/fixture/tool"), patch.object(local, "source", return_value=nullcontext((COMMIT, ROOT))), patch.object(local.Driver, "kubernetes", return_value=nullcontext()), patch.object(local.Driver, "kube", side_effect=read), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["verify"]), 0)
        self.assertTrue(any("application" in command for command in commands))
        for command in commands:
            self.assertFalse(any(item in command for item in ("apply", "delete", "--raw", "promote")))


if __name__ == "__main__":
    unittest.main()
