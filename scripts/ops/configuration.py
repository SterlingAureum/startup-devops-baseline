"""Small environment inventory. Infrastructure and application settings stay in GitOps/IaC."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config/environments.example.yaml"
DELIVERY_CONFIG = ROOT / "delivery/standard/config.json"


class OpsError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise OpsError(message)


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    value = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        require(isinstance(key, str) and key not in value, "Configuration keys must be unique strings")
        value[key] = loader.construct_object(value_node)
    return value


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(text):
    return yaml.load(text, Loader=UniqueLoader)


def mapping(value, allowed, location, required=()):
    require(isinstance(value, dict), location + " must be a mapping")
    require(not set(value) - set(allowed), location + " has unsupported fields (credentials do not belong in this file)")
    require(set(required) <= set(value), location + " is missing required fields")


def text(value, location):
    require(isinstance(value, str) and bool(value.strip()), location + " must be a nonempty string")


def repository_path(value, location):
    text(value, location)
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts and value != ".", location + " must be a repository-relative path")
    return value


def https_url(value, location):
    text(value, location)
    url = urlsplit(value)
    require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
            and not url.query and not url.fragment, location + " must be a credential-free HTTPS URL")


def validate_environment(env):
    mapping(env, ("driver", "delivery_environment", "timeout", "kind", "argocd", "gitops", "aws", "terraform"), "environment", ("driver",))
    require(env["driver"] in ("kind", "aws"), "Supported drivers are kind and aws")
    require(type(env.get("timeout", 900)) is int and env.get("timeout", 900) > 0, "timeout must be a positive integer")
    text(env.get("delivery_environment"), "delivery_environment")
    if env["driver"] == "aws":
        mapping(env.get("aws"), ("expected_account_id", "region", "profile", "role_arn"), "aws", ("expected_account_id", "region"))
        aws = env["aws"]
        require(isinstance(aws["expected_account_id"], str) and re.fullmatch(r"[0-9]{12}", aws["expected_account_id"]), "aws.expected_account_id must be a quoted 12-digit account ID")
        text(aws["region"], "aws.region")
        for key in ("profile", "role_arn"):
            if key in aws:
                text(aws[key], "aws." + key)
        tf = env.get("terraform")
        require(not isinstance(tf, dict) or "backend_file" not in tf,
                "Use terraform.backend.config_file for the S3 backend file")
        mapping(tf, ("root", "variables_file", "backend"), "terraform", ("root", "backend"))
        repository_path(tf["root"], "terraform.root")
        if "variables_file" in tf:
            text(tf["variables_file"], "terraform.variables_file")
        backend = tf["backend"]
        mapping(backend, ("type", "path", "config_file"), "terraform.backend", ("type",))
        require(backend["type"] in ("s3", "local"), "terraform.backend.type must be s3 or local")
        key = "path" if backend["type"] == "local" else "config_file"
        mapping(backend, ("type", key), "terraform.backend", ("type", key))
        text(backend[key], "terraform.backend." + key)
        require("kind" not in env, "An AWS environment must not contain kind settings")
    else:
        require("aws" not in env and "terraform" not in env, "A kind environment must not contain AWS/Terraform settings")
        mapping(env.get("kind"), ("cluster", "node_image", "http_port", "https_port"), "kind", ("cluster", "node_image", "http_port", "https_port"))
        kind = env["kind"]
        require(isinstance(kind["cluster"], str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", kind["cluster"]), "Use a lowercase kind cluster name, at most 63 characters")
        text(kind["node_image"], "kind.node_image")
        ports = [kind["http_port"], kind["https_port"]]
        require(all(type(port) is int and 1 <= port <= 65535 for port in ports) and ports[0] != ports[1], "Use two distinct valid kind host ports")
    if env["driver"] == "kind" or "argocd" in env:
        mapping(env.get("argocd"), ("namespace", "manifest"), "argocd", ("namespace", "manifest"))
        require(isinstance(env["argocd"]["namespace"], str) and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", env["argocd"]["namespace"]), "Invalid Argo CD namespace")
        https_url(env["argocd"]["manifest"], "argocd.manifest")
    if env["driver"] == "kind" or "gitops" in env:
        require(not isinstance(env.get("gitops"), dict) or "root_manifest" not in env["gitops"],
                "Remove gitops.root_manifest from the inventory. Set root_manifest on the selected delivery target")
        mapping(env.get("gitops"), ("repository", "revision", "root_application", "parameters"), "gitops", ("repository", "root_application"))
        gitops = env["gitops"]
        https_url(gitops["repository"], "gitops.repository")
        text(gitops["root_application"], "gitops.root_application")
        if gitops.get("revision") is not None:
            require(isinstance(gitops["revision"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", gitops["revision"])
                    and ".." not in gitops["revision"], "Use a branch, tag or full commit SHA")
        require(isinstance(gitops.get("parameters", {}), dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in gitops.get("parameters", {}).items()), "gitops.parameters must map names to string values")
    return env


@dataclass(frozen=True)
class AwsTarget:
    inventory_name: str
    stage: str
    terraform_root: Path
    delivery_environment: str
    gitops_root: str
    catalog: dict


def delivery_target(env):
    catalog = json.loads(DELIVERY_CONFIG.read_text())
    key = env["delivery_environment"]
    targets = catalog["environments"]
    require(key in targets, f"Unknown delivery environment {key!r} in delivery/standard/config.json")
    manifest = repository_path(targets[key]["root_manifest"], f"delivery environment {key!r} root_manifest")
    if env["driver"] == "kind":
        require(not Path(manifest).is_relative_to("clusters/aws"),
                f"Kind environment cannot select the AWS GitOps root {manifest}")
    return catalog, manifest


def standard_aws_target(name, env, catalog, manifest):
    # The catalog chooses the overlay. The physical Terraform target must agree.
    root = (ROOT / env["terraform"]["root"]).resolve()
    if root.parent == ROOT / "infra/terraform/aws/environments" and root.name in ("dev", "test"):
        expected = f"clusters/aws/overlays/{root.name}/root-app.yaml"
        require(manifest == expected,
                f"Delivery environment {env['delivery_environment']!r} must select {expected} for Terraform root {root}")
        return AwsTarget(name, root.name, root, env["delivery_environment"], manifest, catalog)
    return None


def environment(path, name):
    doc = load_yaml(Path(path).expanduser().read_text())
    mapping(doc, ("schema_version", "environments"), "configuration", ("schema_version", "environments"))
    require(type(doc["schema_version"]) is int and doc["schema_version"] == 2,
            "Inventory requires schema_version: 2. Update your selected entries using config/environments.example.yaml")
    entries = doc["environments"]
    require(isinstance(entries, dict), "environments must be a mapping")
    if name not in entries:
        available = ", ".join(sorted(entries)) or "(none)"
        raise OpsError(f"Unknown environment {name!r}. Available environments: {available}")
    # Validate the selected target only: an unfinished AWS example cannot break local operations.
    return validate_environment(deepcopy(entries[name]))
