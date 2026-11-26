#!/usr/bin/env python3
"""Check an environment PR against a trusted, ordinary CI verification report."""
import argparse
import json
import os
import subprocess
import sys
import zipfile

import yaml

from common import IDENTITY_FIELDS, UniqueLoader, git, Rejected, config, promotion_source, identity, release, repo_path
from image_receipt import require_published
from flow import changed_paths, require_current_source

from verification import reference_mismatch, require_pass, verified_report


def validate_report(report, cfg, source, target, run_id, attempt, *, checked_revision="HEAD"):
    require_pass(report, cfg["application"]["release_name"], source)
    if str(report.get("run_id")) != run_id or str(report.get("run_attempt")) != attempt:
        raise Rejected(reference_mismatch(source, run_id, attempt, report.get("run_id"), report.get("run_attempt")))
    require_current_source(cfg, source, report, checked_revision)
    proposed = identity(target)
    verified = report.get("release")
    if verified != proposed:
        if verified["image"]["digest"] != proposed["image"]["digest"]:
            raise Rejected(f"PR image digest {proposed['image']['digest']} differs from "
                           f"{source} verified digest {verified['image']['digest']}. "
                           "Regenerate the promotion PR from the verified release.")
        missing = object()
        fields = [f"{group}.{key}" for group, keys in IDENTITY_FIELDS.items() for key in keys
                  if verified.get(group, {}).get(key, missing) != proposed[group].get(key, missing)]
        raise Rejected(f"PR release identity differs from the {source} verification "
                       f"({', '.join(fields) or 'unexpected report fields'}). Regenerate the PR from the verified release.")


def configuration_fields(value):
    # Keep unrecognised settings at every level so a release PR cannot smuggle
    # chart configuration into an identity-only change.
    fields = {**IDENTITY_FIELDS, "promotion": ("sourceEnvironment", "verificationRunId", "verificationRunAttempt")}
    result = dict(value)
    for group, keys in fields.items():
        if group in result:
            rest = {key: val for key, val in result.pop(group).items() if key not in keys}
            if rest:
                result[group] = rest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        cfg = config()
        paths = changed_paths(args.base, args.head)
        catalog_path = "delivery/standard/config.json"
        if catalog_path in paths:
            base_catalog = json.loads(git("show", f"{args.base}:{catalog_path}"))
            if any(env["release"] in paths for env in base_catalog["environments"].values()):
                raise Rejected("Change promotion configuration separately from an existing release file")
        for target in cfg["environments"]:
            path = cfg["environments"][target]["release"]
            if path not in paths:
                continue
            value = release(repo_path(path))
            if paths != [path]:
                raise Rejected("A release PR must change only its target release file")
            before = yaml.load(git("show", f"{args.base}:{path}"), Loader=UniqueLoader)
            if configuration_fields(before) != configuration_fields(value):
                raise Rejected("Change deployment settings in environment values via a separate configuration PR")
            source = promotion_source(cfg, target)
            if source is None:
                require_published(os.environ["GITHUB_REPOSITORY"], value)
                if git("diff", "--name-only", value["delivery"]["sourceCommit"], args.base, "--", *cfg["paths"]["application"]):
                    raise Rejected("Application source changed since publication; publish the current application")
                continue
            if target == cfg["promotion"].get("prod") and os.getenv("DELIVERY_PROD_ENABLED") != "true":
                raise Rejected("Production release updates are disabled")
            promotion = value.get("promotion", {})
            if promotion.get("sourceEnvironment") != source:
                raise Rejected(f"Promotion to {target} requires a verified release from {source}")
            run_id = str(promotion.get("verificationRunId", ""))
            attempt = str(promotion.get("verificationRunAttempt", ""))
            report = verified_report(os.environ["GITHUB_REPOSITORY"], run_id, attempt, source)
            validate_report(report, cfg, source, value, run_id, attempt, checked_revision=args.head)
        print("PASS: release changes follow the configured promotion order")
    except (Rejected, KeyError, ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
