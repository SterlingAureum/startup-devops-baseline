#!/usr/bin/env python3
"""Check an environment PR against a trusted, ordinary CI verification report."""
import argparse
import json
import os
import subprocess
import sys
import zipfile

from common import Rejected, config, fingerprint, identity, release, repo_path
from flow import changed_paths, input_fingerprint


from verification import require_pass, verified_report


def validate_report(report, cfg, source, target, run_id, attempt):
    require_pass(report, cfg["application"]["release_name"], source)
    path = repo_path(cfg["environments"][source]["release"])
    if (report.get("verified") is not True or report.get("environment") != source or
            str(report.get("run_id")) != run_id or str(report.get("run_attempt")) != attempt or
            report.get("release") != identity(target) or
            report.get("release_sha256") != fingerprint(path) or
            report.get("inputs_sha256") != input_fingerprint(cfg, source)):
        raise Rejected("Verification does not match the current source release and deployment inputs")


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
