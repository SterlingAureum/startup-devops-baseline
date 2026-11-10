"""Environment-scoped lifecycle entrypoint; AWS execution is not implemented yet."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import yaml

from configuration import DEFAULT_CONFIG, OpsError, environment, require, validate_environment
import local

STEPS = {
    "show": ["read and validate selected environment configuration"],
    "doctor": ["check installed tools"],
    "create": ["create named kind cluster if absent", "save dedicated kubeconfig", "wait for nodes"],
    "install-argocd": ["save dedicated kubeconfig", "install pinned Argo CD", "wait for controllers"],
    "deploy": ["fetch and pin GitOps source", "render root preflight", "apply root Application"],
    "status": ["save dedicated kubeconfig", "read nodes and Argo Applications"],
    "verify": ["read deployed root", "fetch target source", "render declared child Applications", "check nodes, Argo and Application convergence"],
    "connect": ["save dedicated kubeconfig", "merge owned kind entries into selected user config", "switch its current-context"],
    "destroy": ["require exact cluster-name confirmation", "delete named kind cluster", "remove dedicated config; retain shared config"],
    "up": ["fetch and pin GitOps source", "render root preflight", "create", "install-argocd", "deploy", "verify"],
}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("command", choices=STEPS)
    value.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    value.add_argument("--env", default="local")
    value.add_argument("--cluster")
    value.add_argument("--repo-url")
    value.add_argument("--revision", help="Pushed branch/tag/SHA; verify defaults to the deployed pinned commit")
    value.add_argument("--timeout", type=int)
    value.add_argument("--http-port", type=int)
    value.add_argument("--https-port", type=int)
    value.add_argument("--node-image")
    value.add_argument("--argocd-manifest")
    value.add_argument("--confirm")
    value.add_argument("--kubeconfig-file", help="Explicit shared config target for connect only")
    value.add_argument("--dry-run", action="store_true", help="Read config and print phases; invoke no tools and write no files")
    return value


def configure(args, local_only=False):
    env = environment(args.config, args.env)
    if local_only:
        require(env["driver"] == "kind", "local.py only accepts kind environments; use cli.py show to inspect AWS configuration")
    if env["driver"] == "aws":
        require(args.command == "show", "AWS lifecycle execution is pending; this increment supports AWS configuration inspection only")
        require(not any(getattr(args, key) is not None for key in ("cluster", "repo_url", "revision", "timeout", "http_port", "https_port", "node_image", "argocd_manifest", "confirm", "kubeconfig_file")), "AWS inspection does not accept kind command overrides")
        return env
    for argument, section, key in (("cluster", "kind", "cluster"), ("node_image", "kind", "node_image"),
                                   ("http_port", "kind", "http_port"), ("https_port", "kind", "https_port"),
                                   ("repo_url", "gitops", "repository"), ("revision", "gitops", "revision"),
                                   ("argocd_manifest", "argocd", "manifest")):
        if getattr(args, argument) is not None:
            env[section][key] = getattr(args, argument)
    if args.timeout is not None:
        env["timeout"] = args.timeout
    validate_environment(env)
    args.cluster = env["kind"]["cluster"]
    args.node_image = env["kind"]["node_image"]
    args.http_port = env["kind"]["http_port"]
    args.https_port = env["kind"]["https_port"]
    args.repo_url = env["gitops"]["repository"]
    args.revision = env["gitops"].get("revision")
    args.root_manifest = env["gitops"]["root_manifest"]
    args.root_application = env["gitops"]["root_application"]
    args.parameters = env["gitops"].get("parameters", {})
    args.argocd_namespace = env["argocd"]["namespace"]
    args.argocd_manifest = env["argocd"]["manifest"]
    args.timeout = env.get("timeout", 900)
    require(not args.kubeconfig_file or args.command == "connect", "--kubeconfig-file is only valid for connect")
    if args.command in ("deploy", "up"):
        require(bool(args.revision), "Supply --revision or gitops.revision for deploy/up")
    if args.command in ("up", "install-argocd"):
        require(args.argocd_namespace == "argocd", "Pinned bootstrap supports namespace argocd")
    if args.command == "destroy":
        require(args.confirm == args.cluster, "Destroy requires --confirm equal to the selected kind cluster name")
    return env


def tools_for(command):
    if command in ("show",):
        return ()
    if command in ("deploy", "verify", "up", "doctor"):
        return ("kind", "kubectl", "git", "helm") + (("docker",) if command in ("up", "doctor") else ())
    if command == "create":
        return ("docker", "kind", "kubectl")
    if command in ("destroy", "connect"):
        return ("kind",)
    return ("kind", "kubectl")


def children_for(root, directory, args, commit):
    children = local.render_children(root, directory)
    for child in children:
        source = child["spec"]["source"]
        if source.get("repoURL") == args.repo_url:
            require(source.get("targetRevision") == commit, "Same-repository child Application must pin the root commit; configure the parent chart's Git revision parameter")
    return children


def main(argv=None, local_only=False):
    args = parser().parse_args(argv)
    requested_revision = args.revision
    try:
        env = configure(args, local_only)
        if args.command == "show" or args.dry_run:
            print(json.dumps({"environment": args.env, "configuration": env, "command": args.command,
                              "steps": STEPS[args.command], "executed": False}, indent=2))
            return 0
        missing = [tool for tool in tools_for(args.command) if shutil.which(tool) is None]
        require(not missing, "Missing tools: " + ", ".join(missing))
        driver = local.Driver(args)
        if args.command == "doctor":
            print("Required tools are installed; runtime/network readiness is checked during commands")
        elif args.command in ("up", "deploy"):
            with local.source(args) as (commit, directory):
                root = local.root_application(args, commit, directory)
                children = children_for(root, directory, args, commit)
                if args.command == "up":
                    driver.create()
                    driver.install()
                driver.deploy(root)
                if args.command == "up":
                    driver.verify(root, children)
        elif args.command == "verify":
            deployed = driver.deployed_root()
            args.revision = requested_revision or deployed["spec"]["source"]["targetRevision"]
            with local.source(args) as (commit, directory):
                root = local.root_application(args, commit, directory)
                # Preserve deployed Helm inputs (including an older local demo
                # image) when checking an existing environment without redeploying.
                if "helm" in deployed["spec"]["source"]:
                    root["spec"]["source"]["helm"] = deepcopy(deployed["spec"]["source"]["helm"])
                children = children_for(root, directory, args, commit)
                driver.verify(root, children)
        elif args.command == "install-argocd":
            driver.install()
        else:
            getattr(driver, args.command)()
        if args.command in ("up", "create", "install-argocd", "deploy", "status", "verify"):
            print("To use ordinary kubectl, explicitly connect: " + shlex.join([
                "python3", str(Path(__file__).with_name("cli.py")), "connect", "--config",
                str(args.config.expanduser().absolute()), "--env", args.env, "--cluster", args.cluster]))
        return 0
    except (OpsError, OSError, subprocess.SubprocessError, yaml.YAMLError, KeyError, TypeError, ValueError) as error:
        print("FAILED: " + str(error), file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        if isinstance(args.cluster, str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", args.cluster):
            path = local.connections.private_path(args.cluster)
            if path.is_file():
                print("Saved connection; debug with: " + shlex.join([
                    "kubectl", "--kubeconfig", str(path), "--context", "kind-" + args.cluster, "get", "nodes"]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
