"""Match a dev release to the original successful publish job and its image receipt."""
import json
import os
import sys
from pathlib import Path

from common import Rejected
from verification import api, read_artifact, require_source_job


def receipt(repository, commit, image, run_id, attempt):
    return {"schema_version": 1, "repository": repository, "source_commit": commit,
            "image": image, "run_id": run_id, "run_attempt": attempt, "producer_job": "publish"}


def require_published(repository, value):
    delivery, image = value["delivery"], value["image"]
    commit = delivery["sourceCommit"]
    run_id, attempt = delivery.get("workflowRunId"), delivery.get("workflowRunAttempt")
    if not all(isinstance(i, str) and i.isascii() and i.isdecimal() for i in (run_id, attempt)):
        raise Rejected("Dev entry requires the image publish run ID and producing attempt")
    tag = "sha-" + commit[:7]
    if (delivery["sourceRepository"] != repository or image["tag"] != tag
            or value["release"]["applicationVersion"] != tag or "promotion" in value):
        raise Rejected("Dev entry identity differs from the standard image publication")
    path = f"repos/{repository}/actions/runs/{run_id}"
    specific = path + "/attempts/" + attempt
    workflow = api(specific)
    if (workflow.get("path") != ".github/workflows/delivery-image.yaml"
            or workflow.get("event") != "workflow_run" or workflow.get("head_branch") != "main"
            or workflow.get("head_repository", {}).get("full_name") != repository
            or str(workflow.get("id")) != run_id or str(workflow.get("run_attempt")) != attempt):
        raise Rejected("Dev entry requires the trusted main image workflow")
    require_source_job(specific, "publish", attempt, workflow["head_sha"])
    actual = read_artifact(repository, path, f"delivery-image-receipt-{run_id}-{attempt}", "published.json")
    if actual != receipt(repository, commit, image["repository"] + "@" + image["digest"], run_id, attempt):
        raise Rejected("The published image receipt differs from the proposed release")


if __name__ == "__main__":
    record = receipt(os.environ["GITHUB_REPOSITORY"], os.environ["SOURCE_REVISION"], os.environ["IMAGE"],
                     os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"])
    Path(sys.argv[1]).write_text(json.dumps(record, indent=2) + "\n")
