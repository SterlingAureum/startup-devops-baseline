"""Require every applicable current CI job to finish successfully."""
import json
import os
import sys


def validate(results, event):
    mandatory = {"route", "repository", "unit"}
    if any(results.get(name, {}).get("result") != "success" for name in mandatory):
        raise ValueError("A mandatory check did not complete successfully")
    outputs = results["route"].get("outputs", {})
    applicable = set(mandatory)
    for output, job in (("tests", "application"), ("render", "render"), ("platform", "platform"), ("iac", "iac")):
        if outputs.get(output) not in ("true", "false"):
            raise ValueError("Missing or invalid routing output: " + output)
        if outputs[output] == "true":
            applicable.add(job)
    if outputs["render"] == "true":
        environments = json.loads(outputs.get("environments", "null"))
        if not isinstance(environments, list) or not environments or any(
            name not in ("local", "aws-dev", "aws-test", "aws-prod") for name in environments
        ):
            raise ValueError("Rendering requires explicit supported environments")
    if event == "pull_request":
        applicable.add("promotion")
    elif event not in ("push", "workflow_dispatch"):
        raise ValueError("Unexpected CI event")
    for name in applicable:
        if results.get(name, {}).get("result") != "success":
            raise ValueError("Applicable check did not succeed: " + name)
    if any(item.get("result") not in ("success", "skipped") for item in results.values()):
        raise ValueError("A check failed, was cancelled or has an unknown result")


if __name__ == "__main__":
    try:
        validate(json.loads(os.environ["RESULTS"]), os.environ["GITHUB_EVENT_NAME"])
    except (KeyError, TypeError, ValueError) as error:
        sys.exit(str(error))
    print("All applicable current delivery checks passed")
