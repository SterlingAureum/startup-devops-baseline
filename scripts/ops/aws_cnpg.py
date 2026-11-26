"""Read-only progress reporting for the personal AWS PostgreSQL bootstrap."""
import json
import re
import shlex
import time

from configuration import OpsError


def pod_summary(pods):
    lines = []
    log_target = None
    for pod in sorted(pods, key=lambda item: item["metadata"]["name"]):
        meta, status = pod["metadata"], pod.get("status", {})
        if meta.get("deletionTimestamp") or status.get("phase") in ("Succeeded", "Failed"):
            continue  # Finished bootstrap attempts do not describe a current instance.
        name = meta["name"]
        scheduled = next((c for c in status.get("conditions", []) if c["type"] == "PodScheduled"), {})
        if scheduled.get("status") == "False":
            lines.append(f"{name}: {scheduled.get('reason', 'unscheduled')}")
        for container in status.get("initContainerStatuses", []) + status.get("containerStatuses", []):
            if container.get("ready"):
                continue
            state = container.get("state", {})
            if state.get("terminated", {}).get("exitCode") == 0:
                continue
            reason = state.get("waiting", {}).get("reason") or state.get("terminated", {}).get("reason") or "not ready"
            last = container.get("lastState", {}).get("terminated") or state.get("terminated", {})
            restarts = container.get("restartCount", 0)
            detail = f"{name}/{container['name']}: {reason}, restarts={restarts}"
            if "exitCode" in last:
                detail += f", lastExit={last['exitCode']}"
            lines.append(detail)
            if restarts and (log_target is None or container["name"] == "postgres"):
                log_target = (name, container["name"])
    return lines, log_target


def wait_for_cnpg(g, namespace, name):
    resource = f"clusters.postgresql.cnpg.io/{name}"
    description = f"{namespace}/{resource}"
    g.until(f"creation of {description}", lambda: g.obj(namespace, resource))
    started = time.monotonic()
    last_print = started
    last_summary = None
    log_target = None

    def ready():
        nonlocal last_print, last_summary, log_target
        cluster = g.obj(namespace, resource) or {}
        status = cluster.get("status", {})
        condition = next((c for c in status.get("conditions", []) if c.get("type") == "Ready"), {})
        generation = cluster.get("metadata", {}).get("generation", 0)
        observed = condition.get("observedGeneration", status.get("observedGeneration", generation))
        if condition.get("status") == "True" and int(observed) >= int(generation):
            return True
        summary = f"instances ready {status.get('readyInstances', 0)}/{cluster.get('spec', {}).get('instances', '?')}"
        if not cluster:
            summary = "Cluster object absent"
        elif status.get("phase"):
            summary += f", phase={status['phase']}"
        if condition.get("reason"):
            summary += f", Ready={condition.get('status', 'Unknown')} ({condition['reason']})"
        log_target = None
        try:
            raw = g.k("-n", namespace, "get", "pods", "-l", f"cnpg.io/cluster={name}",
                      "-o", "json", "--request-timeout=5s")
            details, log_target = pod_summary(json.loads(raw)["items"])
            if details:
                summary += "; " + "; ".join(details)
        except (OpsError, OSError, json.JSONDecodeError):
            summary += "; Pod status unavailable"
        now = time.monotonic()
        if summary != last_summary or now - last_print >= 60:
            print(f"CNPG [{int(now - started)}s]: {summary}", flush=True)
            last_summary, last_print = summary, now
        return False

    try:
        g.until(f"Ready=True on {description} (timeout {g.timeout}s)", ready)
    except OpsError as error:
        command = ["kubectl", "--kubeconfig", str(g.path), "--context", g.context, "-n", namespace]
        detail = f"Last CNPG observation: {last_summary}" if last_summary else "CNPG readiness could not be observed"
        if log_target:
            pod, container = log_target
            args = ["logs", pod, "-c", container, "--previous", "--tail=30", "--limit-bytes=8192"]
            # Do not echo arbitrary database logs or connection strings into CI logs.
            try:
                tail = g.k("-n", namespace, *args, "--request-timeout=5s", private=True)
                if "wait-for-get-cluster" in tail or "API server to be reachable" in tail:
                    target = re.search(r"dial tcp ([0-9.]+:443): i/o timeout", tail)
                    if target:
                        detail += f". Previous container log: Kubernetes API connection to {target[1]} timed out"
            except (OpsError, OSError):
                pass
            command.extend(args)
        else:
            command.extend(["describe", resource])
        raise OpsError(f"{error}\n{detail}\nInspect: {shlex.join(command)}") from error
