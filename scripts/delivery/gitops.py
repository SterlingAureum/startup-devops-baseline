"""Render the standard single-repository Applications from the proposed Git tree."""
import os
from pathlib import Path
import tempfile

import yaml

from common import ROOT, Rejected, UniqueLoader, load_yaml, release, repo_path, run
from offline import validate


def source(app):
    if app.get("apiVersion") != "argoproj.io/v1alpha1" or app.get("kind") != "Application":
        raise Rejected("Expected an Argo CD Application")
    spec = app["spec"]
    destination = spec["destination"]
    if ("sources" in spec or "source" not in spec or
            destination.get("server") != "https://kubernetes.default.svc" or not destination.get("namespace")):
        raise Rejected("Expected one Git source and an in-cluster destination namespace")
    return spec["source"]


def render_chart(app):
    src = source(app)
    options = src.get("helm", {})
    if (set(src) - {"repoURL", "path", "targetRevision", "helm"} or
            set(options) - {"releaseName", "valueFiles", "values", "valuesObject", "parameters"}):
        raise Rejected("Unsupported Application source or Helm options in the standard render adapter")
    chart = repo_path(src["path"])
    command = ["helm", "template", options.get("releaseName", app["metadata"]["name"]), str(chart),
               "--namespace", app["spec"]["destination"]["namespace"]]
    for name in options.get("valueFiles", []):
        if not isinstance(name, str) or name.startswith(("/", "$")):
            raise Rejected("Expected a chart-relative values file")
        command += ["-f", str(repo_path(str(Path(src["path"]) / name)))]
    with tempfile.TemporaryDirectory() as directory:
        if "valuesObject" in options or "values" in options:
            values = Path(directory) / "values.yaml"
            values.write_text(yaml.safe_dump(options["valuesObject"]) if "valuesObject" in options else options["values"])
            command += ["-f", str(values)]
        seen = set()
        for item in options.get("parameters", []):
            name, value = item["name"], item.get("value", "")
            force = item.get("forceString", False)
            if (not isinstance(name, str) or not name or name in seen or not isinstance(value, str)
                    or type(force) is not bool or "," in value or "$" in value):
                raise Rejected("Expected unique literal scalar Helm parameters: " + str(name))
            seen.add(name)
            command += ["--set-string" if force else "--set", name + "=" + value]
        return run(command, cwd=ROOT, capture_output=True).stdout


def render_environment(cfg, environment):
    env = cfg["environments"][environment]
    app = cfg["application"]
    root = load_yaml(repo_path(env["root_manifest"]))
    src = source(root)
    if not any(repo_path(src["path"]).resolve().is_relative_to(repo_path(folder).resolve())
               and repo_path(env["root_manifest"]).resolve().is_relative_to(repo_path(folder).resolve())
               for folder in env["cluster_paths"]):
        raise Rejected("Root manifest and source must belong to the environment fingerprint")
    repo = src["repoURL"]
    expected_repo = os.environ.get("GITHUB_REPOSITORY")
    if expected_repo and repo.removesuffix(".git").lower() != ("https://github.com/" + expected_repo).lower():
        raise Rejected("Root Git URL differs from the checked repository")
    if src["targetRevision"] not in {"HEAD", cfg["base_branch"]}:
        raise Rejected("Standard CI renders the proposed main tree; root tracks a different revision")
    if environment == "local":
        parent = render_chart(root)
    else:
        if set(src) != {"path", "targetRevision", "repoURL"}:
            raise Rejected("Unsupported Kustomize root overrides")
        parent = run(["kubectl", "kustomize", str(repo_path(src["path"]))], cwd=ROOT, capture_output=True).stdout
    matches = [doc for doc in yaml.load_all(parent, Loader=UniqueLoader)
               if doc and doc.get("kind") == "Application" and doc["metadata"]["name"] == env["application"]
               and doc["metadata"].get("namespace") == root["spec"]["destination"]["namespace"]]
    if len(matches) != 1:
        raise Rejected(f"Expected exactly one child Application {env['application']} under {env['root_manifest']}")
    child = matches[0]
    child_src = source(child)
    options = child_src.get("helm", {})
    expected_files = env["values"] + ([env["release"]] if env["release"] else [])
    files = [str(Path(child_src["path"]) / name) for name in options.get("valueFiles", [])]
    if (child_src["repoURL"] != repo or child_src["targetRevision"] != src["targetRevision"]
            or child_src["path"] != app["chart"] or child["spec"]["destination"]["namespace"] != app["namespace"]
            or options.get("releaseName", env["application"]) != app["release_name"] or files != expected_files):
        raise Rejected(f"{environment}: child Git source, Helm identity or ordered values files differ from the delivery contract")
    text = render_chart(child)
    workload = validate(list(yaml.load_all(text, Loader=UniqueLoader)), environment, app["namespace"],
                        app["metrics_required"], app["environment_annotation"])
    if env["release"]:
        expected = release(repo_path(env["release"]))
        pod = workload["spec"]["template"]
        images = [c["image"] for c in pod["spec"]["containers"] if c["name"] == app["container"]]
        annotations = pod["metadata"]["annotations"]
        fields = {"image-tag": expected["image"]["tag"], "image-digest": expected["image"]["digest"],
                  "application-version": expected["release"]["applicationVersion"],
                  "source-repository": expected["delivery"]["sourceRepository"],
                  "source-commit": expected["delivery"]["sourceCommit"]}
        if expected["delivery"].get("workflowRunId"):
            fields["workflow-run-id"] = str(expected["delivery"]["workflowRunId"])
        if (images != [expected["image"]["repository"] + "@" + expected["image"]["digest"]]
                or any(annotations.get("platform.startup.dev/" + key) != val for key, val in fields.items())):
            raise Rejected(f"{environment}: effective workload identity differs from release file")
    return text
