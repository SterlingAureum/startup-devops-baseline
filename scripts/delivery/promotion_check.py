#!/usr/bin/env python3
"""Check an environment PR against a trusted, ordinary CI verification report."""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import zipfile

from common import Rejected, config, fingerprint, identity, release, repo_path
from flow import changed_paths, input_fingerprint


def api(path, binary=False):
    result = subprocess.run(["gh", "api", path], check=True, capture_output=True)
    return result.stdout if binary else json.loads(result.stdout)


def validate_report(report, cfg, source, target, run_id, attempt):
    path = repo_path(cfg["environments"][source]["release"])
    if (report.get("verified") is not True or report.get("environment") != source or
            str(report.get("run_id")) != run_id or str(report.get("run_attempt")) != attempt or
            report.get("release") != identity(target) or
            report.get("release_sha256") != fingerprint(path) or
            report.get("inputs_sha256") != input_fingerprint(cfg, source)):
        raise Rejected("Verification does not match the current source release and deployment inputs")


def verified_report(repository, run_id, attempt, source):
    if not run_id.isdigit() or not attempt.isdigit():
        raise Rejected("Invalid verification workflow identity")
    path = f"repos/{repository}/actions/runs/{run_id}"
    for _ in range(19):
        workflow = api(path)
        if workflow.get("status") == "completed":
            break
        time.sleep(5)
    if (workflow.get("conclusion") != "success" or workflow.get("head_branch") != "main" or
            workflow.get("head_repository", {}).get("full_name", "").lower() != repository.lower() or
            str(workflow.get("run_attempt")) != attempt or
            workflow.get("event") not in ("push", "workflow_dispatch") or
            workflow.get("path") not in (".github/workflows/delivery-runtime.yaml", ".github/workflows/delivery-promote.yaml")):
        raise Rejected("Verification must come from a successful trusted-main delivery workflow")
    artifacts = api(path + "/artifacts?per_page=100")["artifacts"]
    name = f"delivery-verified-{source}-{run_id}-{attempt}"
    selected = [item for item in artifacts if item["name"] == name and not item["expired"]]
    if len(selected) != 1:
        raise Rejected("Verification report missing or expired; rerun source verification")
    item = selected[0]
    if item["size_in_bytes"] > 1024 * 1024:
        raise Rejected("Unexpected verification artifact size")
    archive = api(f"repos/{repository}/actions/artifacts/{item['id']}/zip", binary=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        if zipped.namelist() != ["verified.json"] or zipped.getinfo("verified.json").file_size > 65536:
            raise Rejected("Unexpected verification artifact contents")
        report = json.loads(zipped.read("verified.json"))
    if report.get("config_revision") != workflow["head_sha"]:
        raise Rejected("Verification checkout differs from its trusted workflow revision")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        cfg = config()
        paths = changed_paths(args.base, args.head)
        for target in ("aws-dev", "aws-test", "aws-prod"):
            path = cfg["environments"][target]["release"]
            if path not in paths:
                continue
            value = release(repo_path(path))
            if paths != [path]:
                raise Rejected("A release PR must change only its target release file")
            if target == "aws-dev":
                continue
            source = {"aws-test": "aws-dev", "aws-prod": "aws-test"}[target]
            if target == "aws-prod" and os.getenv("DELIVERY_PROD_ENABLED") != "true":
                raise Rejected("Production release updates are disabled")
            promotion = value.get("promotion", {})
            if promotion.get("sourceEnvironment") != source:
                raise Rejected("Environment promotion must follow dev -> test -> prod")
            run_id = str(promotion.get("verificationRunId", ""))
            attempt = str(promotion.get("verificationRunAttempt", ""))
            report = verified_report(os.environ["GITHUB_REPOSITORY"], run_id, attempt, source)
            validate_report(report, cfg, source, value, run_id, attempt)
        print("PASS: release changes follow the configured promotion order")
    except (Rejected, KeyError, ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
