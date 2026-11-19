#!/usr/bin/env python3
"""Path routing, Helm checks and small GitOps promotion PRs."""
import argparse
import hashlib
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
from verification import require_pass, verified_report


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
        targets = set()
        for name, env in cfg["environments"].items():
            if (path == env["release"] or path in env["values"] or
                    path.startswith(tuple(env["cluster_paths"]))):
                targets.add(name)
        if not targets and path.startswith((*cfg["paths"]["app_config"], "platform/")):
            targets.update(cfg["environments"])
        if not targets and path.startswith("clusters/"):
            selected.update(cfg["environments"])
        selected.update(targets)
        runtime.update(targets - {"local"})
    if app or shared:
        selected.update(cfg["environments"])
    return {"application": app, "tests": app or shared, "iac": affected("iac") or shared,
            "platform": platform or shared, "render": bool(app or app_config or shared or platform),
            "environments": sorted(selected), "runtime_dev": "aws-dev" in runtime,
            "runtime_test": "aws-test" in runtime, "runtime_prod": "aws-prod" in runtime,
            "dev_release_changed": cfg["environments"]["aws-dev"]["release"] in paths}


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
        if (value["image"].get("repository") == repository and value["image"].get("digest") == digest
                and value["delivery"].get("sourceRepository") == source_repository
                and value["delivery"].get("sourceCommit") == commit):
            return False
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
        require_pass(candidate, cfg["application"]["release_name"], expected_source)
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


def pending_proposal(repository, target, path, prefix, value, candidate):
    """Reuse a reviewed candidate only while its original source evidence is usable."""
    result = run(["gh", "api", "--paginate", "--slurp",
                  f"repos/{repository}/pulls?base=main&state=open&per_page=100"], capture_output=True)
    legacy = f"delivery/{target}/{value['image']['digest'][7:19]}-"
    for page in json.loads(result.stdout):
        for pr in page:
            head = pr["head"]
            if ((head.get("repo") or {}).get("full_name") != repository
                    or not head["ref"].startswith((prefix, legacy))):
                continue
            git("fetch", "--no-tags", "origin", f"refs/pull/{pr['number']}/head")
            previous = yaml.load(git("show", f"FETCH_HEAD:{path}"), Loader=UniqueLoader)
            if any(previous["image"][key] != value["image"][key] for key in ("repository", "digest")):
                continue
            if (previous["delivery"]["sourceRepository"] != value["delivery"]["sourceRepository"]
                    or previous["delivery"]["sourceCommit"] != value["delivery"]["sourceCommit"]):
                raise Rejected(f"Review conflicting source identity in existing PR: {pr['html_url']}")
            if git("diff", "--name-only", "origin/main...FETCH_HEAD").splitlines() != [path]:
                raise Rejected(f"Existing candidate PR has other changes: {pr['html_url']}")
            if candidate:
                if identity(previous) != candidate["release"]:
                    raise Rejected(f"Existing candidate identity changed: {pr['html_url']}")
                proof = previous.get("promotion", {})
                try:
                    source = candidate["environment"]
                    report = verified_report(repository, str(proof["verificationRunId"]),
                                             str(proof["verificationRunAttempt"]), source)
                    require_pass(report, candidate["application_id"], source)
                    if (proof.get("sourceEnvironment") != source or report["release"] != candidate["release"]
                            or report["inputs_sha256"] != candidate["inputs_sha256"]
                            or report["release_sha256"] != candidate["release_sha256"]):
                        raise Rejected("Source inputs changed")
                except (Rejected, KeyError) as error:
                    raise Rejected(f"Review and close stale PR {pr['html_url']} before proposing again: {error}") from error
            return pr["html_url"]
    return None


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
    repository = os.environ["GITHUB_REPOSITORY"]
    app = cfg["application"]["release_name"]
    image = value["image"]
    key = hashlib.sha256(f"{app}/{image['repository']}@{image['digest']}".encode()).hexdigest()
    prefix = f"delivery/{args.target}/{key}/"
    existing = pending_proposal(repository, args.target, target, prefix, value, candidate)
    if existing:
        git("restore", "--", target)
        print(f"Existing promotion PR: {existing}")
        return
    producer = value.get("promotion", {})
    run_id = producer.get("verificationRunId", os.environ["GITHUB_RUN_ID"])
    attempt = producer.get("verificationRunAttempt", "1")
    branch = f"{prefix}{run_id}-{attempt}-{base}"
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    if git("diff", "--name-only").splitlines() != [target]:
        raise Rejected("Promotion must change only the target release file")
    git("add", "--", target)
    git("commit", "-m", f"release: update {args.target} application image")
    git("fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if git("rev-parse", "origin/main") != base:
        raise Rejected("main changed while preparing this PR; rerun")
    if git("ls-remote", "--heads", "origin", f"refs/heads/{branch}"):
        git("fetch", "--no-tags", "origin", f"refs/heads/{branch}")
        if git("rev-parse", "FETCH_HEAD^{tree}") != git("rev-parse", "HEAD^{tree}"):
            raise Rejected("Existing proposal branch differs; inspect it before retrying")
    else:
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
            emit_output("application_id", cfg["application"]["release_name"])
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
