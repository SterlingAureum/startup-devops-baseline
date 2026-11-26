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

from common import (COMMIT, DIGEST, IDENTITY_FIELDS, ROOT, Rejected, UniqueLoader, config, emit_output,
                    fingerprint, git, identity, load_yaml, promotion_chain, promotion_source, release, repo_path, run)
from gitops import render_environment
from image_receipt import require_published
from verification import require_pass, verified_report


def classify(paths, cfg, full_checks=False):
    def affected(group):
        return any(any(path.startswith(prefix) if prefix.endswith(("/", "-")) else path == prefix
                       for prefix in cfg["paths"][group]) for path in paths)
    # New code/config paths fail to the complete current checks. Historical
    # material and ordinary documentation do not replay archived validators.
    def known(path):
        return any(any(path.startswith(prefix) if prefix.endswith(("/", "-")) else path == prefix
                       for prefix in prefixes) for prefixes in cfg["paths"].values())
    documentation = ("README.md", "CHANGELOG.md", "LICENSE")
    shared = full_checks or affected("shared") or any(
        not known(path) and path not in documentation and not path.startswith(("docs/", "archive/"))
        for path in paths
    )
    app = affected("application")
    platform = affected("platform")
    selected = set()
    runtime = []
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
    for name, env in cfg["environments"].items():
        if env.get("runtime_stage") and env["release"] in paths:
            runtime.append(name)
    if app or shared:
        selected.update(cfg["environments"])
    return {"application": app, "tests": app or shared, "iac": affected("iac") or shared,
            "platform": platform or shared, "render": bool(selected),
            "environments": sorted(selected), "runtime_targets": sorted(runtime),
            "dev_release_changed": cfg["promotion"]["dev"] in runtime}


def runtime_matrix(cfg, targets, manual, prod_enabled):
    rows = []
    for name in targets:
        stage = cfg["environments"].get(name, {}).get("runtime_stage")
        if not stage:
            raise Rejected(f"Unknown or ineligible AWS runtime target: {name}")
        if stage == "prod" and not prod_enabled:
            if manual:
                raise Rejected("Production runtime acceptance is disabled")
            continue
        rows.append({"environment": name, "stage": stage})
    return rows


def changed_paths(base, head):
    if not COMMIT.fullmatch(head) or not COMMIT.fullmatch(base):
        raise Rejected("Diff revisions must be full commit SHAs")
    result = run(["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
                 cwd=ROOT, capture_output=True).stdout
    return [path for path in result.split("\0") if path]


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
    chart = repo_path(cfg["application"]["chart"])
    env_files = {repo_path(item) for entry in cfg["environments"].values()
                 for item in [*entry["values"], entry["release"]] if item}
    paths = {repo_path(item) for item in env["values"]}
    for folder in (chart, repo_path("platform"), repo_path("scripts/delivery"),
                   *(repo_path(item) for item in env["cluster_paths"])):
        paths.update(path for path in folder.rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts and path not in env_files)
    settings = {"version": 2, "environment": environment, "deployment": env,
                "application": cfg["application"], "runtime": cfg["runtime"], "branch": cfg["base_branch"]}
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode() + b"\0")
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def require_current_source(cfg, source, report, checked_revision):
    path = cfg["environments"][source]["release"]
    if report.get("release_sha256") != fingerprint(repo_path(path)):
        reason = f"Source release file changed: {path}"
    elif report.get("inputs_sha256") != input_fingerprint(cfg, source):
        reason = f"Deployment inputs for {source} changed"
    else:
        return
    raise Rejected(f"{reason}. Verified revision {report['config_revision']}, "
                   f"checked revision {checked_revision}. Reverify {source} and generate a new promotion PR.")


def prepare_release(cfg, target, candidate=None, image=None, commit=None, source_repository=None, run_id=None,
                    *, checked_revision="HEAD"):
    expected_source = promotion_source(cfg, target)
    target_path = repo_path(cfg["environments"][target]["release"])
    value = load_yaml(target_path)
    if expected_source is None:
        if candidate is not None:
            raise Rejected("Dev requires a published image")
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
        attempt = os.getenv("PUBLISH_ATTEMPT")
        if not attempt or not attempt.isdecimal():
            raise Rejected("Dev entry requires the publish job attempt")
        incoming = {"image": {"repository": repository, "tag": tag, "digest": digest},
                    "release": {"applicationVersion": tag},
                    "delivery": {"sourceRepository": source_repository, "sourceCommit": commit,
                                 "workflowRunId": str(run_id), "workflowRunAttempt": attempt}}
        value.pop("promotion", None)
    else:
        if not candidate or candidate.get("environment") != expected_source or candidate.get("verified") is not True:
            raise Rejected("Promotion requires a successful verification of the preceding environment")
        require_pass(candidate, cfg["application"]["release_name"], expected_source)
        if target == cfg["promotion"].get("prod") and os.getenv("DELIVERY_PROD_ENABLED") != "true":
            raise Rejected("Production promotion is disabled")
        source_path = repo_path(cfg["environments"][expected_source]["release"])
        current = release(source_path)
        require_current_source(cfg, expected_source, candidate, checked_revision)
        if identity(current) != candidate["release"]:
            raise Rejected(f"Verified artifact identity differs from the release in {source_path.name} for "
                           f"{expected_source}. Reverify {expected_source} before proposing this release.")
        if identity(release(target_path)) == identity(current):
            return False
        incoming = identity(current)
        value.setdefault("promotion", {}).update(sourceEnvironment=expected_source,
                                                 verificationRunId=str(candidate["run_id"]),
                                                 verificationRunAttempt=str(candidate["run_attempt"]))
    for group, keys in IDENTITY_FIELDS.items():
        for key in keys:
            value[group].pop(key, None)
        value[group].update(incoming[group])
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
            else:
                require_published(repository, previous)
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
        if args.target != cfg["promotion"]["dev"] or not args.commit:
            raise Rejected("Only a built image can enter dev directly")
        # An old image build must not overwrite a newer source change.
        source_paths = cfg["paths"]["application"]
        if git("diff", "--name-only", args.commit, base, "--", *source_paths):
            raise Rejected("Application changed after this build; use the newer build")
    changed = prepare_release(cfg, args.target, candidate, args.image, args.commit,
                              os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"], checked_revision=base)
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
    route.add_argument("--full-checks", action="store_true")
    runtime_route = sub.add_parser("runtime-route")
    inputs = runtime_route.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--environment")
    inputs.add_argument("--base")
    runtime_route.add_argument("--head")
    promote = sub.add_parser("promotion-route")
    promote.add_argument("--source-stage", choices=("dev", "test"))
    render = sub.add_parser("render")
    render.add_argument("--environment", required=True)
    sub.add_parser("platform")
    sub.add_parser("test-app")
    pr = sub.add_parser("pr")
    pr.add_argument("--target", required=True)
    pr.add_argument("--candidate")
    pr.add_argument("--image")
    pr.add_argument("--commit")
    args = parser.parse_args()
    try:
        cfg = config()
        if args.command == "classify":
            result = classify(changed_paths(args.base, args.head), cfg, args.full_checks)
            emit_output("application_id", cfg["application"]["release_name"])
            for name, value in result.items():
                emit_output(name, json.dumps(value, separators=(",", ":")))
            print(json.dumps(result, indent=2))
        elif args.command == "runtime-route":
            if args.environment is not None:
                targets = [args.environment or cfg["promotion"]["dev"]]
            else:
                if not args.head:
                    raise Rejected("Push routing requires --head")
                targets = classify(changed_paths(args.base, args.head), cfg)["runtime_targets"]
            rows = runtime_matrix(cfg, targets, args.environment is not None,
                                  os.getenv("DELIVERY_PROD_ENABLED") == "true")
            for row in rows:
                row["test_target"] = cfg["promotion"]["test"] if row["environment"] == cfg["promotion"]["dev"] else ""
            emit_output("matrix", json.dumps(rows, separators=(",", ":")))
            print(json.dumps(rows))
        elif args.command == "promotion-route":
            chain = promotion_chain(cfg)
            target = chain[0]
            if args.source_stage:
                source = cfg["promotion"][args.source_stage]
                index = chain.index(source) + 1
                if index == len(chain):
                    raise Rejected(f"No promotion destination configured after {source}")
                target = chain[index]
                if target == cfg["promotion"].get("prod") and os.getenv("DELIVERY_PROD_ENABLED") != "true":
                    raise Rejected("Production promotion is disabled")
                emit_output("source", source)
            emit_output("target", target)
            print(f"{source} -> {target}" if args.source_stage else f"Image entry: {target}")
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
