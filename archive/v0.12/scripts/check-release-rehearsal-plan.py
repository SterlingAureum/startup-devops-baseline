#!/usr/bin/env python3
"""Offline plan validation only. Never contacts a cluster or authorizes release."""
import argparse
import json
import re
from pathlib import Path

BRANCH = "feature/v0.11-observability-sre-baseline"


def validate(plan):
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object")
    required = {"environment", "branch", "source_commit", "context", "review_reference",
                "operator", "recovery_owner", "evidence_directory", "approval_policy",
                "baseline", "candidate", "failure_scenario", "max_duration_seconds"}
    if set(plan) != required:
        raise ValueError("Plan fields must match the supplied template exactly")
    if plan["environment"] not in ("local", "aws-dev", "aws-test"):
        raise ValueError("Prod is deferred; allowed environments: local/aws-dev/aws-test")
    if plan["branch"] != BRANCH:
        raise ValueError("Feature branch required; no main integration authorized")
    if not isinstance(plan["source_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", plan["source_commit"]):
        raise ValueError("Full source commit SHA required")
    for key in ("context", "review_reference", "operator", "recovery_owner", "evidence_directory"):
        value = plan[key]
        if not isinstance(value, str) or not value.strip() or any(x in value for x in ("<", ">", "REPLACE", "TODO")):
            raise ValueError(f"Concrete {key} required")
    if not Path(plan["evidence_directory"]).is_absolute():
        raise ValueError("Absolute private evidence directory required")
    if plan["approval_policy"] != "human-governed":
        raise ValueError("This rehearsal retains the current human-governed policy")
    if plan["failure_scenario"] != "candidate-slo-gate-rejection":
        raise ValueError("Only the planned candidate SLO rejection scenario is supported")
    limit = plan["max_duration_seconds"]
    if type(limit) is not int or not 60 <= limit <= 3600:
        raise ValueError("Duration must be an integer between 60 and 3600 seconds")
    for key in ("baseline", "candidate"):
        release = plan[key]
        if not isinstance(release, dict) or set(release) != {"application_version", "image"}:
            raise ValueError(f"{key} must contain application_version and image")
        version, image = release["application_version"], release["image"]
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", version) or version.startswith("REPLACE"):
            raise ValueError(f"Concrete {key} application version required")
        if not isinstance(image, str) or not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}", image):
            raise ValueError(f"Immutable {key} image digest required")
    if plan["baseline"]["application_version"] == plan["candidate"]["application_version"]:
        raise ValueError("Candidate version must differ from baseline")
    return {"status": "plan_validated_offline", "runtime_qualified": False,
            "execution_authorized": False, "environment": plan["environment"],
            "checks_not_performed": ["git_identity", "cluster_identity", "image_availability",
                                     "runtime_readiness", "approval_authenticity", "recovery_execution"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(json.loads(args.plan.read_text())), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Plan rejected: {exc}\n")


if __name__ == "__main__":
    main()
