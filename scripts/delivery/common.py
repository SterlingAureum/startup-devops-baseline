"""Small shared helpers; no imports from the historical qualification system."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "delivery/standard/config.json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class Rejected(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise Rejected(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path):
    return yaml.load(Path(path).read_text(), Loader=UniqueLoader)


def config(path=DEFAULT_CONFIG):
    value = json.loads(Path(path).read_text())
    if value.get("base_branch") != "main":
        raise Rejected("This first workflow adapter supports protected main only")
    for item in [value["application"]["directory"], value["application"]["chart"]]:
        repo_path(item)
    for name, env in value["environments"].items():
        stage = env.get("runtime_stage")
        if stage is not None and (stage not in ("dev", "test", "prod") or not env["release"]
                                  or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)):
            raise Rejected(f"Invalid AWS runtime target: {name}")
        if name == "aws-prod" and stage not in (None, "prod"):
            raise Rejected("The standard production target requires the prod runtime stage")
    promotion_chain(value)
    return value


def promotion_chain(cfg):
    """Resolve ordered release targets for the standard personal or enterprise path."""
    stages = cfg.get("promotion")
    if not isinstance(stages, dict) or set(stages) not in ({"dev", "test"}, {"dev", "test", "prod"}):
        raise Rejected("promotion requires dev and test targets and accepts optional prod")
    targets = []
    for stage in ("dev", "test", "prod"):
        if stage in stages:
            target = stages[stage]
            if not isinstance(target, str) or cfg["environments"].get(target, {}).get("runtime_stage") != stage:
                raise Rejected(f"promotion.{stage} must select a delivery target with runtime_stage {stage}")
            targets.append(target)
    paths = [repo_path(env["release"]).resolve() for env in cfg["environments"].values() if env["release"]]
    if len(paths) != len(set(paths)):
        raise Rejected("Delivery environments must have distinct release files")
    return targets


def promotion_source(cfg, target):
    chain = promotion_chain(cfg)
    if target not in chain:
        raise Rejected(f"Release target outside the configured promotion path: {target}")
    if target == chain[0]:
        return None
    return chain[chain.index(target) - 1]


def repo_path(value):
    if not isinstance(value, str) or not value:
        raise Rejected("Expected a nonempty repository-relative path")
    path = ROOT / value
    if Path(value).is_absolute() or not path.resolve().is_relative_to(ROOT):
        raise Rejected("Expected a path within the repository")
    return path


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def git(*args):
    return run(["git", *args], cwd=ROOT, capture_output=True).stdout.strip()


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def release(path):
    value = load_yaml(path)
    image = value["image"]
    delivery = value["delivery"]
    if not DIGEST.fullmatch(image.get("digest", "")):
        raise Rejected("Release must pin a SHA-256 image digest")
    repository = image.get("repository", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9./_-]*", repository) or "/" not in repository:
        raise Rejected("Release must name a lowercase registry/repository without a tag")
    if not COMMIT.fullmatch(delivery.get("sourceCommit", "")):
        raise Rejected("Release must identify its source commit")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", delivery.get("sourceRepository", "")):
        raise Rejected("Release must identify its source repository")
    if not isinstance(value["release"].get("applicationVersion"), str) or not value["release"]["applicationVersion"]:
        raise Rejected("Release must identify its application version")
    return value


IDENTITY_FIELDS = {"image": ("repository", "tag", "digest"), "release": ("applicationVersion",),
                   "delivery": ("sourceRepository", "sourceCommit", "workflowRunId", "workflowRunAttempt")}


def identity(value):
    return {group: {k: value[group][k] for k in keys if k in value[group]}
            for group, keys in IDENTITY_FIELDS.items()}


def emit_output(name, value):
    import os
    if "\n" in str(value) or "\r" in str(value):
        raise Rejected("Workflow outputs must be single-line values")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"{name}={value}\n")
