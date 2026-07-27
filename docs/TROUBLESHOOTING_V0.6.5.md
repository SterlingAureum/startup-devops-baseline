# v0.6.5 PostgreSQL Application Failover Troubleshooting

## Scope

This runbook records the issues encountered while validating the v0.6.5
demo-api PostgreSQL integration and CloudNativePG primary failover workflow on
AWS:

- demo-api Pods were Ready but did not contain the new `src.database` module;
- `validate-demo-api-postgresql.sh` appeared to hang after the Pods were Ready;
- PostgreSQL returned the primary address with a `/32` host mask, while the
  validators compared it with the plain Kubernetes Pod IP;
- Kubernetes printed an Endpoints deprecation warning during an otherwise
  valid check.

These symptoms were not caused by PostgreSQL availability, the synchronized
application credential, the RW Service, or network connectivity.

The final acceptance messages are:

```text
demo-api PostgreSQL connection validation passed.
CloudNativePG primary failover and demo-api reconnect validation passed.
```

## Safety Notes

- Do not run these scripts with `bash -x`. They read Kubernetes Secret objects,
  and shell tracing can expose credential values.
- Do not print or decode `DATABASE_URL` or the source `fqdn-uri`.
- Do not delete demo-api Pods until the Deployment image has been verified.
  Recreating a Pod with the same old image does not deploy the v0.6.5 code.
- Do not delete PostgreSQL Pods, PVCs, or PVs while diagnosing the
  non-disruptive validator.
- Run `run-cloudnative-pg-failover-test.sh` only after the non-disruptive
  validation passes and only with the documented confirmation input.

## Quick Triage

Use the following order to separate image-promotion, application, database, and
validation-contract failures.

### 1. Check the declared and running image

```bash
rg -n 'tag:|APP_VERSION' \
  apps/demo-api/helm/values-aws-dev.yaml

kubectl get deployment demo-api \
  -n startup-apps \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'

kubectl get pods \
  -n startup-apps \
  -l 'app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api' \
  -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image,IMAGE_ID:.status.containerStatuses[0].imageID
```

The Helm value, Deployment image, and both Pod images must reference the same
immutable `sha-<short-commit>` tag.

### 2. Check the application database module directly

```bash
for pod in $(
  kubectl get pods \
    -n startup-apps \
    -l 'app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api' \
    --field-selector=status.phase=Running \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
); do
  echo "==> ${pod}"

  kubectl exec -n startup-apps "${pod}" -- \
    python -m src.database health
done
```

The command returns only sanitized connection metadata. A healthy result looks
similar to:

```json
{
  "database": "app",
  "in_recovery": false,
  "server_address": "10.20.11.112/32",
  "server_port": 5432,
  "status": "ok",
  "user": "app"
}
```

### 3. Resolve the current primary and RW Service endpoint

```bash
PRIMARY_POD="$(
  kubectl get pods \
    -n data-platform \
    -l 'cnpg.io/cluster=postgresql-baseline,cnpg.io/instanceRole=primary' \
    -o jsonpath='{.items[0].metadata.name}'
)"

PRIMARY_IP="$(
  kubectl get pod "${PRIMARY_POD}" \
    -n data-platform \
    -o jsonpath='{.status.podIP}'
)"

echo "primary_pod=${PRIMARY_POD}"
echo "primary_ip=${PRIMARY_IP}"

kubectl get endpoints postgresql-baseline-rw \
  -n data-platform \
  -o wide
```

Interpret the evidence as follows:

| Evidence | Meaning |
|---|---|
| `No module named src.database` | The running image does not contain the v0.6.5 application code. |
| Direct health command returns `status=ok` | The application credential, DNS, Service routing, and PostgreSQL connection work. |
| `database=app` and `user=app` | demo-api uses the CloudNativePG application identity rather than the superuser. |
| `in_recovery=false` | The connection terminates on the writable primary. |
| RW endpoint equals the primary Pod IP | The `postgresql-baseline-rw` Service selects the current primary correctly. |
| Health succeeds but the validator waits | Inspect address formatting and the validator comparison contract. |

## 1. Running Pods Do Not Contain `src.database`

### Symptoms

Both demo-api Pods were Running and Ready, but the direct application check
failed:

```text
/usr/local/bin/python: No module named src.database
command terminated with exit code 1
```

### Cause

The Deployment still referenced a pre-v0.6.5 image. The source repository
contained `apps/demo-api/src/database.py`, but that source commit had not yet
been built and promoted to `apps/demo-api/helm/values-aws-dev.yaml`.

The image workflow automatically builds pushes to `main` that change
`apps/demo-api/**`. A push to
`feature/v0.6-cloudnativepg-data-platform` requires a manual
`workflow_dispatch` run for that branch.

Because the old application did not import or provide `src.database`, it could
remain Ready while the v0.6.5 validator waited for functionality that did not
exist in the container.

### Diagnosis

Confirm that the module exists and is committed:

```bash
test -f apps/demo-api/src/database.py &&
  echo "database.py exists"

git show HEAD:apps/demo-api/src/database.py >/dev/null &&
  echo "database.py is committed"
```

Compare the current commit with the deployed tag:

```bash
git log -1 --oneline

rg -n 'tag:|APP_VERSION' \
  apps/demo-api/helm/values-aws-dev.yaml

kubectl get deployment demo-api \
  -n startup-apps \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

### Resolution

Push the feature branch:

```bash
git push origin feature/v0.6-cloudnativepg-data-platform
```

Run the demo-api image publishing workflow manually against:

```text
feature/v0.6-cloudnativepg-data-platform
```

After the workflow succeeds, verify and promote the immutable image:

```bash
BUILD_SHA="$(git rev-parse --short=7 HEAD)"
IMAGE_TAG="sha-${BUILD_SHA}"

IMAGE_TAG="${IMAGE_TAG}" \
./scripts/check-ghcr-demo-api-image.sh

VALUES_FILE=apps/demo-api/helm/values-aws-dev.yaml \
IMAGE_TAG="${IMAGE_TAG}" \
./scripts/set-demo-api-image.sh
```

Commit the promotion:

```bash
git add apps/demo-api/helm/values-aws-dev.yaml

git commit -m "release: update aws-dev demo-api image to ${IMAGE_TAG}"

git push origin feature/v0.6-cloudnativepg-data-platform
```

Apply the GitOps revision and wait for the Deployment:

```bash
./scripts/deploy-aws-dev-root-app.sh

kubectl rollout status deployment/demo-api \
  -n startup-apps \
  --timeout=10m
```

Deleting the old Pods without changing the Deployment image is not a fix. The
replacement Pods will use the same old image.

## 2. The Validator Appears to Hang

### Symptoms

The validator reached:

```text
==> Checking each demo-api PostgreSQL endpoint
```

and then produced no output for a long time, even though:

- the demo-api Application was `Synced/Healthy`;
- the Deployment rollout completed;
- both demo-api Pods were Ready;
- PostgreSQL was available.

### Cause

The validator checks two demo-api Pods sequentially. For each Pod it can retry
for:

```text
READY_TIMEOUT_SECONDS=1200
```

The failed HTTP or JSON result is suppressed during the retry loop. The
worst-case wait is therefore approximately 40 minutes for two Pods, with no
intermediate diagnostic output.

This behavior makes a deterministic contract mismatch look like an
infrastructure hang.

### Diagnosis

It is safe to stop the non-disruptive validator with `Ctrl+C`.

Run the direct database health command from the Quick Triage section. If both
Pods immediately return valid JSON, compare these fields with the current
primary:

```text
status          = ok
database        = app
user            = app
server_address  = primary Pod IP, optionally followed by /32
server_port     = 5432
in_recovery     = false
```

Also test the HTTP endpoint directly:

```bash
for pod in $(
  kubectl get pods \
    -n startup-apps \
    -l 'app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api' \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
); do
  echo "==> ${pod}"

  kubectl exec -n startup-apps "${pod}" -- \
    python -c \
    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/db/health", timeout=15).read().decode())'
done
```

### Resolution

Fix the first deterministic failure instead of increasing the timeout. For the
confirmed v0.6.5 incident, the failure was the `/32` address representation
described in the next section.

Future validator improvements should:

- fail immediately when `src.database` is missing;
- report the last sanitized health response before timing out;
- use one bounded deadline for the whole check or report progress per Pod;
- continue suppressing connection strings and Secret values.

## 3. PostgreSQL Address Contains `/32`

### Symptoms

The direct health check succeeded and connected to the correct primary, but
the validator continued retrying:

```text
server_address = 10.20.11.112/32
primary_ip     = 10.20.11.112
```

### Cause

demo-api obtains the address from:

```sql
inet_server_addr()::text
```

PostgreSQL represents this `inet` host value with its `/32` IPv4 mask. The
Kubernetes Pod API returns the same address without a mask.

The original validators used exact string comparison:

```text
10.20.11.112/32 != 10.20.11.112
```

The addresses identify the same host. PostgreSQL, the RW Service, and demo-api
were all operating correctly; only the validation contract was wrong.

### Resolution

Normalize the address before comparing it in:

```text
scripts/validate-demo-api-postgresql.sh
scripts/run-cloudnative-pg-failover-test.sh
```

Change the `jq` field from:

```jq
.server_address // "",
```

to:

```jq
((.server_address // "") | split("/")[0]),
```

Validate both scripts:

```bash
rg -n -C 3 'server_address' \
  scripts/validate-demo-api-postgresql.sh \
  scripts/run-cloudnative-pg-failover-test.sh

bash -n scripts/validate-demo-api-postgresql.sh
bash -n scripts/run-cloudnative-pg-failover-test.sh
```

Rerun the non-disruptive check:

```bash
./scripts/validate-demo-api-postgresql.sh
```

Expected result:

```text
demo-api PostgreSQL connection validation passed.
```

The same normalization is required in the guarded failover script. Otherwise
the preflight or post-promotion application reconnection check can wait for the
full timeout even after demo-api has connected to the new primary.

## 4. Endpoints Deprecation Warning

### Symptoms

Kubernetes printed a warning while the validator inspected:

```text
postgresql-baseline-rw
```

The warning states that the core `v1 Endpoints` API is deprecated and
recommends EndpointSlice.

### Interpretation

This warning does not mean that the RW Service has failed, and it does not
explain the validator wait. The current Endpoints object still resolves to the
primary Pod IP.

Confirm the live routing:

```bash
kubectl get endpoints postgresql-baseline-rw \
  -n data-platform \
  -o wide
```

EndpointSlice migration is a future compatibility improvement. It is not
necessary to rerun the v0.6.5 failover drill solely because this warning was
printed.

## Final Verification

After correcting the deployed image and address normalization, run the
non-disruptive chain:

```bash
./scripts/validate-demo-api-postgresql.sh
./scripts/validate-all.sh
```

Then run the guarded Pod-level primary failover drill:

```bash
./scripts/run-cloudnative-pg-failover-test.sh
```

Type:

```text
failover-primary
```

The final drill must prove:

- a committed marker survives primary replacement;
- a replica is promoted to primary;
- `postgresql-baseline-rw` moves to the new primary;
- demo-api reconnects and can perform a new write;
- the former primary returns as a replica;
- the former primary reuses its original PVC, PV, and EBS volume;
- persistence, backup, and application validators still pass.

Expected final output:

```text
CloudNativePG primary failover and demo-api reconnect validation passed.
```

This is a Pod-level failover exercise. It does not test EC2 termination,
Availability Zone failure, regional disaster recovery, or a production SLO.

## Lessons for Future Changes

- Treat source commit, built image, promoted image tag, and running image ID as
  separate acceptance boundaries.
- A Ready Pod proves that its current application is healthy; it does not prove
  that the intended source revision was deployed.
- Use immutable SHA image tags and verify the GHCR artifact before updating
  GitOps values.
- Expose deterministic application errors before entering a long retry loop.
- Normalize typed network addresses before comparing them with Kubernetes
  plain-string IP fields.
- Keep Secret comparisons silent and never debug credential-handling scripts
  with shell tracing.
- Keep the primary failover test outside `validate-all.sh` because it
  intentionally deletes the current primary Pod.

## References

- [CloudNativePG application connections](https://cloudnative-pg.github.io/docs/1.30/applications/)
- [CloudNativePG failure modes](https://cloudnative-pg.io/docs/1.30/failure_modes/)
- [PostgreSQL network address functions](https://www.postgresql.org/docs/17/functions-net.html)
- [Kubernetes EndpointSlices](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/)
