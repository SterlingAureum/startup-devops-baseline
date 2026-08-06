# v0.6.3 PostgreSQL Backup Troubleshooting

## Scope

This runbook records the issues encountered while validating the v0.6.3
CloudNativePG backup foundation on AWS:

- PostgreSQL physical base backups to Amazon S3;
- continuous WAL archiving;
- IRSA authentication;
- Barman Cloud Plugin instance sidecars;
- Argo CD reconciliation;
- the v0.6.3 backup validation script.

The final runtime acceptance message was:

```text
CloudNativePG S3 base backup and WAL archiving validation passed.
```

## Quick Triage

Use the following order to separate infrastructure, plugin, GitOps, and
validation-script failures:

```bash
kubectl get cluster,pods,backup -n data-platform

kubectl get application \
  cert-manager cloudnative-pg barman-cloud-plugin postgresql-baseline \
  -n argocd

kubectl get deployment -n cnpg-system

kubectl get cluster postgresql-baseline \
  -n data-platform \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
```

Interpret the results as follows:

| Evidence | Meaning |
|---|---|
| `Ready=True` | The PostgreSQL cluster is operational. |
| `ContinuousArchiving=True` | The WAL archiver can use the ObjectStore and write WAL data. |
| Backup CR fails with `EOF` and the plugin sidecar restarts | Inspect the instance-side Barman container for OOM or a process crash. |
| Backup test passes but the validator waits | Inspect Argo CD synchronization before investigating S3 again. |
| Application is `Healthy/OutOfSync` at the current Git revision | Look for controller-added or normalized fields in the live resource. |

## 1. Base Backup Fails with EOF

### Symptoms

The backup selected a PostgreSQL replica and started normally, but failed
shortly afterward with a plugin connection error:

```text
EOF
```

At the same time:

- the PostgreSQL Cluster remained Ready;
- continuous WAL archiving remained healthy;
- the PostgreSQL container did not restart;
- `plugin-barman-cloud` restarted several times.

This combination indicates an instance-side plugin failure rather than a
general S3, IRSA, ObjectStore, or PostgreSQL failure.

### Diagnosis

Inspect all container termination states:

```bash
kubectl get pod postgresql-baseline-2 \
  -n data-platform \
  -o jsonpath='{range .status.containerStatuses[*]}{.name}{" restart="}{.restartCount}{" lastReason="}{.lastState.terminated.reason}{" exitCode="}{.lastState.terminated.exitCode}{"\n"}{end}{range .status.initContainerStatuses[*]}{.name}{" restart="}{.restartCount}{" lastReason="}{.lastState.terminated.reason}{" exitCode="}{.lastState.terminated.exitCode}{"\n"}{end}'
```

Read the previous plugin log rather than the default PostgreSQL container log:

```bash
kubectl logs postgresql-baseline-2 \
  -n data-platform \
  -c plugin-barman-cloud \
  --previous \
  --tail=300
```

The confirmed termination state was:

```text
reason=OOMKilled
exitCode=137
```

### Cause

The ObjectStore allowed two concurrent base-backup jobs while limiting the
instance-side Barman process to 128 MiB:

```yaml
data:
  compression: lz4
  jobs: 2

resources:
  requests:
    memory: 128Mi
  limits:
    memory: 128Mi
```

This limit was insufficient for a compressed physical base backup.

### Resolution

Update
`clusters/aws/base/data-platform/postgresql/object-store.yaml`:

```yaml
spec:
  configuration:
    data:
      compression: lz4
      jobs: 1

  instanceSidecarConfiguration:
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi
```

Update the corresponding validator contracts:

```text
ObjectStore: true:lz4:2:lz4:1:7d
Resources:   100m:500m:256Mi:512Mi
```

After Argo CD applies the ObjectStore change, allow CloudNativePG to roll the
database Pods so every instance-side plugin is recreated with the new resource
settings.

Verify the live settings before rerunning a backup:

```bash
kubectl get objectstore postgresql-baseline-backup \
  -n data-platform \
  -o jsonpath='jobs={.spec.configuration.data.jobs} requests={.spec.instanceSidecarConfiguration.resources.requests} limits={.spec.instanceSidecarConfiguration.resources.limits}{"\n"}'
```

## 2. PostgreSQL Application Remains OutOfSync

### Symptoms

The backup test succeeded, the PostgreSQL Pods used the corrected sidecar
resources, and the Application was Healthy, but it remained OutOfSync:

```text
postgresql-baseline   OutOfSync   Healthy
```

The Git branch and Argo CD Application referenced the same commit. The latest
sync operation had succeeded, but repeated auto-heal attempts continued.

Restarting the PostgreSQL Pods did not resolve the status.

### Diagnosis

Confirm that Argo CD has observed the latest Git commit:

```bash
git fetch origin

git rev-parse origin/feature/v0.6-cloudnativepg-data-platform

kubectl get application postgresql-baseline \
  -n argocd \
  -o jsonpath='{.status.sync.revision}{"\n"}'
```

List only the resources that Argo CD considers OutOfSync:

```bash
kubectl get application postgresql-baseline -n argocd -o json |
  jq -r '
    .status.resources[]
    | select(.status != "Synced")
    | [.group, .kind, .namespace, .name, .status]
    | @tsv
  '
```

Inspect the live plugin specification:

```bash
kubectl get cluster postgresql-baseline \
  -n data-platform \
  -o json |
  jq '.spec.plugins'
```

The live Cluster contained:

```yaml
enabled: true
```

but the Git manifest omitted this field.

### Cause

CloudNativePG defaulted the Barman plugin's `enabled` field to `true`. Argo CD
then compared the controller-normalized live resource with the Git manifest
and repeatedly detected a difference.

A successful sync operation does not guarantee that the Application will stay
Synced when another controller subsequently adds or normalizes fields.

### Resolution

Declare the default explicitly in
`clusters/aws/base/data-platform/postgresql/cluster.yaml`:

```yaml
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      enabled: true
      isWALArchiver: true
      parameters:
        barmanObjectName: postgresql-baseline-backup
```

Push the change and request a hard refresh:

```bash
kubectl annotate application postgresql-baseline \
  -n argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite

kubectl get application postgresql-baseline -n argocd -w
```

Expected status:

```text
postgresql-baseline   Synced   Healthy
```

Pod restarts do not fix this class of problem because it is a declarative
desired-state difference, not a stale process.

## 3. Validation Appears to Hang

### Symptoms

`run-cloudnative-pg-backup-test.sh` passed, but
`validate-cloudnative-pg-backup.sh` waited for a long time after several
messages similar to:

```text
condition met
```

The wait later emitted an HTTP/2 watch error or reached its timeout.

### Cause

The validator checks four Argo CD Applications in sequence and waits for both
Synced and Healthy:

1. `cert-manager`;
2. `cloudnative-pg`;
3. `barman-cloud-plugin`;
4. `postgresql-baseline`.

The first three Applications satisfied both conditions. The validator then
waited for the fourth Application to become Synced, but
`postgresql-baseline` was still OutOfSync because of the plugin field drift
described above.

The HTTP/2 watch disconnect was a symptom of the long-running `kubectl wait`,
not a backup or S3 failure.

### Resolution

Inspect the Application status directly:

```bash
kubectl get application \
  cert-manager cloudnative-pg barman-cloud-plugin postgresql-baseline \
  -n argocd
```

Resolve the OutOfSync resource before rerunning the validator. Do not rerun the
base backup solely because an Application synchronization wait timed out.

## 4. Validator Uses the Wrong Barman Deployment Name

### Symptom

After the Application checks passed, the validator reported:

```text
deployments.apps "barman-cloud" not found
```

### Cause

The Helm-generated Deployment name includes the Argo CD Application or Helm
release name:

```text
barman-cloud-plugin-barman-cloud
```

The validator incorrectly used:

```text
barman-cloud
```

### Resolution

Use the live Deployment name in both the rollout and image lookup:

```bash
kubectl rollout status \
  deployment/barman-cloud-plugin-barman-cloud \
  --namespace cnpg-system \
  --timeout="${WAIT_TIMEOUT}"
```

```bash
BARMAN_IMAGE="$(
  kubectl get deployment barman-cloud-plugin-barman-cloud \
    --namespace cnpg-system \
    --output jsonpath='{.spec.template.spec.containers[?(@.name=="barman-cloud")].image}'
)"
```

Confirm the installed resources when a chart-generated name is uncertain:

```bash
kubectl get deployment -n cnpg-system
```

## 5. Validator Rejects the Correct Plugin Image

### Symptom

The Barman Deployment was Ready, but the validator reported:

```text
The Barman Cloud plugin image is not pinned to the expected release.
```

### Cause

The validator expected a tag containing:

```text
:0.13.0
```

The official image used:

```text
ghcr.io/cloudnative-pg/plugin-barman-cloud:v0.13.0
```

The missing `v` in the validation condition caused a false failure. The
fallback that accepted any digest also did not prove that the expected release
was deployed.

### Resolution

Use an exact release assertion:

```bash
EXPECTED_BARMAN_IMAGE="ghcr.io/cloudnative-pg/plugin-barman-cloud:v0.13.0"

BARMAN_IMAGE="$(
  kubectl get deployment barman-cloud-plugin-barman-cloud \
    --namespace cnpg-system \
    --output jsonpath='{.spec.template.spec.containers[?(@.name=="barman-cloud")].image}'
)"

if [[ "${BARMAN_IMAGE}" != "${EXPECTED_BARMAN_IMAGE}" ]]; then
  echo "Unexpected Barman Cloud plugin image." >&2
  echo "Expected: ${EXPECTED_BARMAN_IMAGE}" >&2
  echo "Actual:   ${BARMAN_IMAGE}" >&2
  exit 1
fi
```

This was a validator defect. It did not require restarting the plugin
Deployment or the PostgreSQL Pods.

## Final Verification

Run the focused backup test first:

```bash
./scripts/run-cloudnative-pg-backup-test.sh
```

Expected result:

```text
CloudNativePG S3 base backup and WAL archiving test passed.
```

Then run the full backup validator:

```bash
./scripts/validate-cloudnative-pg-backup.sh
```

Expected result:

```text
CloudNativePG S3 base backup and WAL archiving validation passed.
```

Finally run the repository-wide validation:

```bash
./scripts/validate-all.sh
```

The v0.6.3 backup foundation is complete only when:

- all four Argo CD Applications are Synced and Healthy;
- the Barman plugin Deployment is Ready;
- all PostgreSQL instance-side plugin containers use the corrected resources;
- `ContinuousArchiving=True`;
- at least one physical base backup is completed;
- the S3 prefix contains both base-backup and WAL objects;
- both focused backup scripts pass.

## Lessons for Future Versions

- Treat `ContinuousArchiving=True` as evidence for the WAL path, not proof that
  a physical base backup has enough memory.
- Inspect the specific failing sidecar and its previous logs; the default
  `kubectl logs POD` output only shows the PostgreSQL container.
- A Healthy but OutOfSync Application usually points to desired-state drift,
  defaulted fields, or mutation by another controller.
- Do not use Pod restarts to repair GitOps drift.
- Derive or verify Helm-generated resource names before hard-coding them in
  validation scripts.
- Validate pinned images against the exact tag or digest expected by the
  release contract.
