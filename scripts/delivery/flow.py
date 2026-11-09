#!/usr/bin/env python3
"""Path routing, Helm checks and small GitOps promotion PRs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml

from common import (COMMIT, DIGEST, ROOT, Rejected, UniqueLoader, config, emit_output,
                    fingerprint, git, identity, load_yaml, release, repo_path, run)
from offline import validate


def classify(paths, cfg):
    def affected(group):
        return any(any(path.startswith(prefix) if prefix.endswith(("/", "-")) else path == prefix
                       for prefix in cfg["paths"][group]) for path in paths)
    # New code/config paths fail to the complete current checks. Historical
    # material and ordinary documentation do not replay archived validators.
    def known(path):
        return any(any(path.startswith(prefix) if prefix.endswith(("/", "-")) else path == prefix
                       for prefix in prefixes) for prefixes in cfg["paths"].values())
    documentation = ("README.md", "CHANGELOG.md", "LICENSE")
    shared = affected("shared") or any(
        not known(path) and path not in documentation and not path.startswith(("docs/", "archive/"))
        for path in paths
    )
    app = affected("application")
    platform = affected("platform")
    app_config = affected("app_config")
    selected = set()
    runtime = set()
    for path in paths:
        specific = False
        for name, env in cfg["environments"].items():
            if path in env["values"] + ([env["release"]] if env["release"] else []):
                selected.add(name)
                if name != "local":
                    runtime.add(name)
                specific = True
        if not specific and any(path.startswith(prefix) for prefix in cfg["paths"]["app_config"]):
            selected.update(cfg["environments"])
            runtime.update({"aws-dev", "aws-test"})
    if app or shared or platform:
        selected.update(cfg["environments"])
    if platform:
        runtime.update({"aws-dev", "aws-test"})
    return {"application": app, "tests": app or shared, "iac": affected("iac") or shared,
            "platform": platform or shared, "render": bool(app or app_config or shared or platform),
            "environments": sorted(selected), "runtime_dev": "aws-dev" in runtime,
            "runtime_test": "aws-test" in runtime, "runtime_prod": "aws-prod" in runtime}


def changed_paths(base, head):
    if not COMMIT.fullmatch(head) or not COMMIT.fullmatch(base):
        raise Rejected("Diff revisions must be full commit SHAs")
    result = run(["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
                 cwd=ROOT, capture_output=True).stdout
    return [path for path in result.split("\0") if path]


def render_environment(cfg, environment):
    app = cfg["application"]
    env = cfg["environments"][environment]
    command = ["helm", "template", app["release_name"], str(repo_path(app["chart"])),
               "--namespace", app["namespace"]]
    for path in env["values"] + ([env["release"]] if env["release"] else []):
        command += ["-f", str(repo_path(path))]
    if environment == "local":
        # Honor the actual local parent Application's Helm parameter overrides.
        parent = run(["helm", "template", "local-platform", "clusters/local/platform"],
                     cwd=ROOT, capture_output=True).stdout
        child = next(item for item in yaml.load_all(parent, Loader=UniqueLoader)
                     if item and item.get("kind") == "Application"
                     and item["metadata"]["name"] == env["application"])
        for item in child["spec"]["source"]["helm"].get("parameters", []):
            command += ["--set" if item["name"].endswith((".enabled", "Seconds")) else "--set-string",
                        f"{item['name']}={item['value']}"]
    text = run(command, cwd=ROOT, capture_output=True).stdout
    validate(list(yaml.load_all(text, Loader=UniqueLoader)), environment, app["namespace"],
             app["metrics_required"], app["environment_annotation"])
    return text


def platform_check():
    charts = [path.parent for folder in ("platform", "clusters/local")
              for path in (ROOT / folder).rglob("Chart.yaml")]
    for chart in sorted(charts):
        run(["helm", "lint", str(chart)], cwd=ROOT)
        rendered = run(["helm", "template", "platform-check", str(chart)], cwd=ROOT, capture_output=True).stdout
        list(yaml.load_all(rendered, Loader=UniqueLoader))
    for environment in ("dev", "test", "prod"):
        rendered = run(["kubectl", "kustomize", f"clusters/aws/overlays/{environment}"],
                       cwd=ROOT, capture_output=True).stdout
        objects = [item for item in yaml.load_all(rendered, Loader=UniqueLoader) if item]
        seen = set()
        for item in objects:
            key = (item["apiVersion"], item["kind"], item["metadata"].get("namespace"), item["metadata"]["name"])
            if key in seen:
                raise Rejected(f"Duplicate rendered platform identity: {key}")
            seen.add(key)


def input_fingerprint(cfg, environment):
    """Bind runtime acceptance to effective deployment inputs, not unrelated app edits."""
    import hashlib
    env = cfg["environments"][environment]
    paths = {repo_path("delivery/standard/config.json"), *[repo_path(path) for path in env["values"]]}
    for folder in (cfg["application"]["chart"], "platform", "clusters", "scripts/delivery"):
        paths.update(path for path in repo_path(folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and "/values/releases/" not in str(path))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def prepare_release(cfg, target, candidate=None, image=None, commit=None, source_repository=None, run_id=None):
    target_path = repo_path(cfg["environments"][target]["release"])
    value = load_yaml(target_path)
    if target == "aws-dev" and candidate is None:
        if not isinstance(image, str) or "@" not in image or not isinstance(commit, str):
            raise Rejected("Dev entry requires a built image@digest and source commit")
        repository, digest = image.rsplit("@", 1)
        if not DIGEST.fullmatch(digest) or not COMMIT.fullmatch(commit):
            raise Rejected("Invalid built image or source commit")
        tag = f"sha-{commit[:7]}"
        value.update({"image": {"repository": repository, "tag": tag, "digest": digest},
                      "release": {"applicationVersion": tag},
                      "delivery": {"sourceRepository": source_repository, "sourceCommit": commit,
                                   "workflowRunId": str(run_id)}})
        value.pop("promotion", None)
    else:
        expected_source = {"aws-test": "aws-dev", "aws-prod": "aws-test"}.get(target)
        if not candidate or candidate.get("environment") != expected_source or candidate.get("verified") is not True:
            raise Rejected("Promotion requires a successful verification of the preceding environment")
        if target == "aws-prod" and os.getenv("DELIVERY_PROD_ENABLED") != "true":
            raise Rejected("Production promotion is disabled")
        source_path = repo_path(cfg["environments"][expected_source]["release"])
        current = release(source_path)
        if (fingerprint(source_path) != candidate["release_sha256"] or
                identity(current) != candidate["release"] or
                input_fingerprint(cfg, expected_source) != candidate["inputs_sha256"]):
            raise Rejected("Source deployment inputs changed after verification; verify again")
        if identity(release(target_path)) == identity(current):
            return False
        value.update(identity(current))
        value["promotion"] = {"sourceEnvironment": expected_source,
                              "verificationRunId": str(candidate["run_id"]),
                              "verificationRunAttempt": str(candidate["run_attempt"])}
    original = target_path.read_text()
    target_path.write_text(yaml.safe_dump(value, sort_keys=False))
    release(target_path)
    return target_path.read_text() != original


def create_pr(args, cfg):
    # This command is called only from trusted main workflows, never from PR code.
    if os.getenv("GITHUB_REF") != "refs/heads/main":
        raise Rejected("PR creation must run from protected main")
    if not os.getenv("DELIVERY_PR_TOKEN"):
        raise Rejected("Configure DELIVERY_PR_TOKEN before enabling automated PR creation")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise Rejected("PR creation requires a clean tracked worktree")
    git("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    git("checkout", "--detach", "origin/main")
    base = git("rev-parse", "HEAD")
    # Read routing from freshly fetched main, never an older caller checkout.
    cfg = config()
    candidate = json.loads(Path(args.candidate).read_text()) if args.candidate else None
    if candidate is None:
        if args.target != "aws-dev" or not args.commit:
            raise Rejected("Only a built image can enter dev directly")
        # An old image build must not overwrite a newer source change.
        source_paths = cfg["paths"]["application"]
        if git("diff", "--name-only", args.commit, base, "--", *source_paths):
            raise Rejected("Application changed after this build; use the newer build")
    changed = prepare_release(cfg, args.target, candidate, args.image, args.commit,
                              os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])
    if not changed:
        print("Target already uses this release; no PR needed")
        return
    render_environment(cfg, args.target)
    target = cfg["environments"][args.target]["release"]
    value = release(repo_path(target))
    image_id = value["image"]["digest"].split(":")[1][:12]
    # One PR per invocation; never force-push or mutate a PR awaiting review.
    branch = f"delivery/{args.target}/{image_id}-{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    git("switch", "-c", branch)
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    if git("diff", "--name-only").splitlines() != [target]:
        raise Rejected("Promotion must change only the target release file")
    git("add", "--", target)
    git("commit", "-m", f"release: update {args.target} application image")
    git("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if git("rev-parse", "origin/main") != base:
        raise Rejected("main changed while preparing this PR; rerun")
    git("push", "origin", f"HEAD:refs/heads/{branch}")
    body = (f"Update **{args.target}** to `{value['image']['repository']}@{value['image']['digest']}`.\n\n"
            f"Source: `{value['delivery']['sourceRepository']}@{value['delivery']['sourceCommit']}`.\n\n"
            "Only the target release file changes. Environment parameters remain independent.\n"
            "Merge after required checks and review; this workflow never merges its own PR.\n")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md") as stream:
        stream.write(body)
        stream.flush()
        result = run(["gh", "pr", "create", "--repo", os.environ["GITHUB_REPOSITORY"], "--base", "main",
                      "--head", branch, "--title", f"release: promote application to {args.target}",
                      "--body-file", stream.name], cwd=ROOT, capture_output=True)
    print(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("classify")
    route.add_argument("--base", required=True)
    route.add_argument("--head", required=True)
    render = sub.add_parser("render")
    render.add_argument("--environment", choices=["local", "aws-dev", "aws-test", "aws-prod"], required=True)
    sub.add_parser("platform")
    sub.add_parser("test-app")
    pr = sub.add_parser("pr")
    pr.add_argument("--target", choices=["aws-dev", "aws-test", "aws-prod"], required=True)
    pr.add_argument("--candidate")
    pr.add_argument("--image")
    pr.add_argument("--commit")
    args = parser.parse_args()
    try:
        cfg = config()
        if args.command == "classify":
            result = classify(changed_paths(args.base, args.head), cfg)
            for name, value in result.items():
                emit_output(name, json.dumps(value, separators=(",", ":")))
            print(json.dumps(result, indent=2))
        elif args.command == "render":
            render_environment(cfg, args.environment)
            print(f"PASS: rendered application for {args.environment}")
        elif args.command == "platform":
            platform_check()
        elif args.command == "test-app":
            command = cfg["application"]["test_command"]
            if command:
                run(command, cwd=repo_path(cfg["application"]["directory"]))
            else:
                print("Application business-test hook explicitly disabled in repository configuration")
        else:
            create_pr(args, cfg)
    except (Rejected, KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
