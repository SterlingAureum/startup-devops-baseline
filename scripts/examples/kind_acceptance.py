"""Record demo-api observations for the hosted two-revision kind rehearsal."""
import argparse
import json
import os
from pathlib import Path
import sys

import demo_api as demo


def record(args, outcome):
    options = demo.parser().parse_args(["verify", "--revision", args.revision, "--repo-url", args.repo_url,
                                        "--cluster", args.cluster, "--timeout", "1500"])
    demo.validate_options(options)
    driver = demo.Driver(options)
    with demo.verification_source(options) as (commit, directory):
        outcome["observed"] = driver.verify(commit, source_root=directory)
        if args.previous_report:
            previous = json.loads(Path(args.previous_report).read_text())
            old, new = previous["observed"], outcome["observed"]
            if (previous["result"] != "passed" or previous["cluster"] != args.cluster
                    or previous["run_id"] != outcome["run_id"] or previous["run_attempt"] != outcome["run_attempt"]
                    or old["gitops_revision"] == commit or old["stable_rs"] == new["stable_rs"]
                    or set(old["pod_image_ids"]) & set(new["pod_image_ids"])):
                raise demo.LocalError("Expected distinct stable releases and local images in the same rehearsal")
            prior_commit = old["gitops_revision"]
            # Ask the same live verifier to accept A's image on B's stable root.
            # Only the stable-Pod identity rejection is the expected outcome.
            try:
                driver.verify(commit, source_root=directory, expected_image_commit=prior_commit)
            except demo.ImageMismatch as error:
                outcome["wrong_image"] = {"expected_source": prior_commit, "reason": str(error)}
            else:
                raise demo.LocalError("Unexpectedly accepted the previous image on the current root")
            options.revision = prior_commit
            with demo.verification_source(options) as (previous, old_tree):
                try:
                    driver.verify(previous, source_root=old_tree)
                except demo.DifferentRootRevision as error:
                    outcome["replaced_root"] = str(error)
                else:
                    raise demo.LocalError("Unexpectedly accepted the previous pinned root")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cluster", "repo-url", "revision", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--previous-report")
    args = parser.parse_args()
    outcome = {"kind": "kind-rehearsal", "result": "failed", "cluster": args.cluster,
               "repository": args.repo_url, "requested_revision": args.revision,
               "run_id": os.getenv("GITHUB_RUN_ID"), "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT")}
    try:
        record(args, outcome)
        outcome["result"] = "passed"
    except Exception as error:
        outcome["reason"] = str(error)
        raise
    finally:
        Path(args.output).write_text(json.dumps(outcome, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
