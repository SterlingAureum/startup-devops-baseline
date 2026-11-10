"""Private persistent connection files and explicit, conservative kubeconfig merging."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import yaml

from configuration import load_yaml, require

OWNER = "startup-devops-baseline/managed-kind-v1"
SECTIONS = ("clusters", "users", "contexts")


def atomic_write(path, contents):
    path = Path(path).expanduser().absolute()
    require(not path.is_symlink(), "Refusing to replace a symlink: " + str(path))
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def private_path(cluster):
    return Path.home() / ".kube/startup-devops-baseline" / (cluster + ".yaml")


def target_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser().absolute()
    paths = [part for part in os.environ.get("KUBECONFIG", "").split(os.pathsep) if part]
    require(len(paths) <= 1, "Multiple KUBECONFIG files: choose one with --kubeconfig-file")
    return Path(paths[0]).expanduser().absolute() if paths else Path.home() / ".kube/config"


def indexed(doc, section):
    items = doc.get(section, []) or []
    require(isinstance(items, list), "Invalid kubeconfig " + section)
    value = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"] not in value,
                "Invalid or duplicate kubeconfig entry in " + section)
        value[item["name"]] = item
    return value


def fingerprint(entry):
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def kind_config(contents, cluster):
    doc = load_yaml(contents)
    require(isinstance(doc, dict) and doc.get("kind") == "Config" and doc.get("apiVersion") == "v1", "kind returned an invalid kubeconfig")
    name = "kind-" + cluster
    for section in SECTIONS:
        require(set(indexed(doc, section)) == {name}, "kind kubeconfig contains unexpected named entries")
    context = indexed(doc, "contexts")[name].get("context", {})
    require(context.get("cluster") == name and context.get("user") == name, "kind context points to unexpected entries")
    doc["current-context"] = name
    return doc


def merge(existing, incoming, cluster):
    """Reject unowned collisions; update previous exports while preserving unrelated entries."""
    require(isinstance(existing, dict), "Existing kubeconfig must be a mapping")
    require(existing.get("kind", "Config") == "Config" and existing.get("apiVersion", "v1") == "v1", "Unsupported kubeconfig format")
    merged = deepcopy(existing)
    name = "kind-" + cluster
    extensions = indexed(merged, "extensions")
    marker = extensions.get(OWNER, {"name": OWNER, "extension": {"entries": {}}})
    require(isinstance(marker.get("extension"), dict) and isinstance(marker["extension"].get("entries"), dict), "Invalid managed-kind ownership record")
    record = marker["extension"]["entries"].get(name, {})
    require(isinstance(record, dict), "Invalid managed-kind entry record")
    hashes = {}
    for section in SECTIONS:
        current = indexed(merged, section)
        replacement = indexed(incoming, section)[name]
        previous = current.get(name)
        field = {"clusters": "cluster", "users": "user", "contexts": "context"}[section]
        if previous is not None:
            # Existing exports with identical connection data can be adopted.
            # Preserve optional settings such as the user's context namespace.
            payload = previous.get(field)
            same = payload == replacement[field]
            if section == "contexts" and isinstance(payload, dict):
                same = (not set(payload) - (set(replacement[field]) | {"namespace", "extensions"})
                        and all(payload.get(k) == v for k, v in replacement[field].items()))
            require(same or record.get(section) == fingerprint(previous),
                    "Unmanaged or modified same-name kubeconfig entry: " + name + " (" + section + "). Resolve it or choose another cluster name/config file")
            replacement = deepcopy(previous)
            replacement[field].update(indexed(incoming, section)[name][field])
        current[name] = replacement
        merged[section] = list(current.values())
        hashes[section] = fingerprint(replacement)
    marker["extension"]["entries"][name] = hashes
    extensions[OWNER] = marker
    merged["extensions"] = list(extensions.values())
    merged.update({"apiVersion": "v1", "kind": "Config", "current-context": name})
    return merged


def connect(incoming, cluster, explicit=None):
    path = target_path(explicit)
    require(path != private_path(cluster).absolute(), "Shared target must differ from the dedicated connection file")
    require(not path.is_symlink(), "Refusing to replace a symlink: " + str(path))
    before = path.read_bytes() if path.exists() else None
    existing = load_yaml(before.decode()) if before and before.strip() else {}
    merged = merge(existing, incoming, cluster)
    contents = yaml.safe_dump(merged, sort_keys=False)
    # Catch changes observed during the merge; do not silently discard them.
    require((path.read_bytes() if path.exists() else None) == before, "kubeconfig changed during merge; rerun connect")
    if before is not None:
        descriptor, backup = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(before)
        print("Kubeconfig backup: " + backup)
    atomic_write(path, contents)
    print("Connected context kind-" + cluster + " in " + str(path))
    return path
