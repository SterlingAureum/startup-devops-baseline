"""Serialize the checked route and consume it from an exact trusted checks run."""
import argparse
import json
import os
from pathlib import Path
import re


def flag(outputs, key):
    value = outputs[key]
    if value not in ("true", "false"):
        raise ValueError(f"Invalid route output {key}")
    return value == "true"


def record(outputs, env):
    event = env["GITHUB_EVENT_NAME"]
    on_main = env["GITHUB_REF"] == "refs/heads/main"
    if not outputs["application_id"]:
        raise ValueError("Missing application ID in the checked route")
    automatic = event == "push" and flag(outputs, "application")
    requested = event == "workflow_dispatch" and env["REQUEST_PUBLISH"] == "true"
    runtime = json.loads(outputs["runtime_targets"])
    if not isinstance(runtime, list) or not all(isinstance(name, str) for name in runtime):
        raise ValueError("Invalid runtime target list")
    return {
        "schema_version": 1, "application_id": outputs["application_id"],
        "repository": env["GITHUB_REPOSITORY"], "event": event,
        "ref": env["GITHUB_REF"], "base": outputs["base"], "head": env["GITHUB_SHA"],
        "producer": {"run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"],
                     "job": "quality-gates"},
        "routed_checks": {key: flag(outputs, key) for key in ("tests", "iac", "platform", "render")},
        "render_environments": json.loads(outputs["environments"]),
        "push_runtime_targets": runtime if event == "push" and on_main else [],
        "propose_test_on_verified_dev": event == "push" and on_main and flag(outputs, "dev_release_changed"),
        "publish_image": on_main and (automatic or requested),
    }


def publish_intent(plan, parent, repository):
    expected = {
        "repository": repository, "head": parent["head_sha"], "event": parent["event"],
        "ref": "refs/heads/main",
        "producer": {"run_id": str(parent["id"]), "run_attempt": str(parent["run_attempt"]),
                     "job": "quality-gates"},
    }
    if (parent["conclusion"] != "success" or parent["event"] not in ("push", "workflow_dispatch")
            or parent["head_branch"] != "main" or parent["head_repository"]["full_name"] != repository
            or parent["path"] != ".github/workflows/delivery-validate.yaml"):
        raise ValueError("Unexpected upstream checks run")
    if (type(plan["schema_version"]) is not int or plan["schema_version"] != 1
            or any(plan.get(key) != value for key, value in expected.items())
            or not re.fullmatch(r"[0-9a-f]{40}", plan["base"])
            or type(plan["publish_image"]) is not bool):
        raise ValueError("Plan does not match the successful upstream checks run")
    return plan["publish_image"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "consume"])
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.action == "consume":
        parent = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["workflow_run"]
        publish = publish_intent(json.loads(args.file.read_text()), parent, os.environ["GITHUB_REPOSITORY"])
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            print("application=" + json.dumps(publish), file=stream)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            print(f"Consumed checks plan from run {parent['id']}, attempt {parent['run_attempt']}. "
                  f"Checked revision: `{parent['head_sha']}`. Publish requested: `{publish}`.", file=stream)
        return
    plan = record(json.loads(os.environ["RESULTS"])["route"]["outputs"], os.environ)
    content = json.dumps(plan, indent=2)
    args.file.write_text(content + "\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
        print("### Checked delivery plan\n\n```json\n" + content + "\n```", file=stream)


if __name__ == "__main__":
    main()
