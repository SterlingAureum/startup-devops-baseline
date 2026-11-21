"""Recover the standard ESO consumer Application after an initial webhook registration race."""
import json
import re

from configuration import OpsError

APP = "applications.argoproj.io/external-secrets-startup-apps"
EXTERNAL = "externalsecrets.external-secrets.io/demo-api-postgresql"
WEBHOOK = "external-secrets-webhook"


def wait_for_consumer(g):
    retried = None

    def read():
        nonlocal retried
        app = g.obj("argocd", APP)
        if not app:
            return None
        status = app.get("status", {})
        op = status.get("operationState", {})
        revision = status.get("sync", {}).get("revision")
        result = op.get("syncResult", {})
        if not app.get("operation") and op.get("phase") in ("Failed", "Error"):
            failed = [r for r in result.get("resources", []) if r.get("status") == "SyncFailed"]
            reason = op.get("message", "sync failed")
            signature = (op.get("startedAt"), op.get("finishedAt"), result.get("revision"))
            if retried == signature:
                return None  # Argo has accepted the patch but still reports the old status.
            expected = {"SecretStore": "aws-secrets-manager", "ExternalSecret": "demo-api-postgresql"}
            if (retried or not failed or not re.fullmatch(r"[0-9a-f]{40}", revision or "")
                    or result.get("revision") != revision or any(
                        r.get("kind") not in expected or expected[r["kind"]] != r.get("name")
                        or f'service "{WEBHOOK}" not found' not in r.get("message", "")
                        or "external-secrets-webhook.external-secrets.svc" not in r["message"] for r in failed)):
                raise OpsError(f"external-secrets-startup-apps sync failed at {revision}: {reason}")
            if not g.obj("external-secrets", "service/" + WEBHOOK):
                return None
            slices = json.loads(g.k("-n", "external-secrets", "get", "endpointslices.discovery.k8s.io",
                                    "-l", "kubernetes.io/service-name=" + WEBHOOK, "-o", "json"))
            if not any(e.get("conditions", {}).get("ready") is True and e.get("addresses")
                       for s in slices["items"] for e in s.get("endpoints", [])):
                return None
            policy = app["spec"].get("syncPolicy", {})
            operation = {"sync": {"revision": revision, "syncOptions": policy.get("syncOptions", [])}}
            patch = [{"op": "test", "path": "/metadata/resourceVersion", "value": app["metadata"]["resourceVersion"]},
                     {"op": "add", "path": "/operation", "value": operation}]
            try:
                g.k("-n", "argocd", "patch", APP, "--type=json", "-p", json.dumps(patch))
            except OpsError as error:
                # The controller can change status while the endpoint check is in progress.
                if "(Conflict)" in str(error) or ("test failed" in str(error) and "resourceVersion" in str(error)):
                    return None
                raise
            print(f"Retried external-secrets-startup-apps at {revision} after webhook became ready", flush=True)
            retried = signature
            return None
        if g.obj("startup-apps", "secretstores.external-secrets.io/aws-secrets-manager"):
            return g.obj("startup-apps", EXTERNAL)
        return None

    g.ready("startup-apps", "crd/externalsecrets.external-secrets.io", "Established")
    g.ready("startup-apps", "crd/secretstores.external-secrets.io", "Established")
    return g.until("external-secrets-startup-apps to apply SecretStore and ExternalSecret", read)
