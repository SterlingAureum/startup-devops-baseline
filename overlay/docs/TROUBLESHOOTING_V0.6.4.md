# v0.6.4 PostgreSQL QoS and Pod Refresh Troubleshooting

## Scope

This runbook records the validation issue encountered after the v0.6.4
CloudNativePG recovery and PITR implementation:

- `validate-all.sh` failed inside
  `validate-cloudnative-pg-persistence.sh`;
- all three PostgreSQL instances remained Ready;
- Argo CD reported `postgresql-baseline` as `Synced/Healthy`;
- updated Barman sidecar resources were present in the ObjectStore;
- the existing PostgreSQL Pods did not roll automatically;
- a controlled CloudNativePG restart recreated the Pods with `Guaranteed` QoS.

This was not a persistence, scheduling, backup, recovery, PITR, or Argo CD
failure. It was a stale-Pod and validation-contract issue.

## Symptoms

The unified validation reached the persistence validator:

```bash
./scripts/validate-all.sh
```

and reported:

```text
PostgreSQL Pod postgresql-baseline-* has invalid capacity placement.
```

However, runtime inspection showed that:

- all three Pods were `2/2 Running`;
- all Pods had zero restarts;
- all Pods used `database-ondemand` nodes;
- all nodes used On-Demand capacity and `workload=database`;
- the PostgreSQL Application was `Synced/Healthy`;
- `kubectl get pods -w` showed no rolling update.

## Quick Triage

Check the Application, Pods, QoS classes, and placement separately:

```bash
kubectl get application postgresql-baseline -n argocd

kubectl get pods \
  -n data-platform \
  -l cnpg.io/cluster=postgresql-baseline \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[*].ready,QOS:.status.qosClass,NODE:.spec.nodeName

kubectl get nodes \
  -l karpenter.sh/nodepool=database-ondemand \
  -L workload,karpenter.sh/nodepool,karpenter.sh/capacity-type,topology.kubernetes.io/zone
```

Interpret the evidence as follows:

| Evidence | Meaning |
|---|---|
| Application is `Synced/Healthy` | The declared Kubernetes resources have reconciled. It does not prove that existing database Pods were recreated. |
| ObjectStore contains the new resources | The desired Barman sidecar configuration is live. |
| Pod age has not changed | Existing Pods still use their previously created Pod specifications. |
| Pod QoS is `Burstable` | At least one container does not meet the equal CPU and memory request/limit contract required for `Guaranteed`. |
| NodePool, capacity type, workload label, and zone are correct | The validator's placement error is a combined-condition message rather than proof of a scheduling failure. |

## Root Cause

### 1. The validator combined QoS and placement checks

The persistence validator checked the following conditions together:

```bash
if [[ "${qos_class}" != "Guaranteed" || \
      "${workload_label}" != "database" || \
      "${nodepool_label}" != "${DATABASE_NODE_POOL}" || \
      "${capacity_type}" != "on-demand" || \
      -z "${pod_zone}" ]]; then
  echo "PostgreSQL Pod ${pod_name} has invalid capacity placement." >&2
  exit 1
fi
```

The node placement was valid. The failed condition was:

```text
qos_class != Guaranteed
```

The error text therefore made a QoS mismatch look like a Karpenter placement
failure.

### 2. The v0.6.3 OOM fix changed the Pod to Burstable

The earlier Barman sidecar OOM correction used unequal requests and limits:

```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

Kubernetes assigns `Guaranteed` QoS only when every container has CPU and
memory requests and limits, and each request equals its corresponding limit.
Because the Barman sidecar did not meet that rule, the entire PostgreSQL Pod
became `Burstable`.

### 3. ObjectStore synchronization did not recreate existing Pods

The final ObjectStore configuration restored equal requests and limits:

```yaml
instanceSidecarConfiguration:
  retentionPolicyIntervalSeconds: 1800
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

Argo CD successfully synchronized this change, but the existing Pods retained
their old Pod specifications and QoS class. A Pod cannot change from
`Burstable` to `Guaranteed` without being recreated.

The Barman Cloud Plugin documentation states that ObjectStore sidecar updates
take effect during Cluster reconciliation and *could* generate a rollout. A
rollout should therefore be verified, not assumed.

`kubectl get pods -w` only watches resource events. It does not request a
restart.

## Resolution

### 1. Keep the final Guaranteed resource contract

Use equal requests and limits in:

```text
clusters/aws/base/data-platform/postgresql/object-store.yaml
```

```yaml
instanceSidecarConfiguration:
  retentionPolicyIntervalSeconds: 1800
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 512Mi
```

Update the backup validator contract accordingly:

```bash
"${SIDECAR_RESOURCES}" != "500m:500m:512Mi:512Mi"
```

### 2. Confirm the live ObjectStore before restarting

```bash
kubectl get objectstore.barmancloud.cnpg.io \
  postgresql-baseline-backup \
  -n data-platform \
  -o jsonpath='requests={.spec.instanceSidecarConfiguration.resources.requests}{" limits="}{.spec.instanceSidecarConfiguration.resources.limits}{"\n"}'
```

Do not restart until the output contains:

```text
cpu:500m
memory:512Mi
```

for both requests and limits.

### 3. Trigger a controlled CloudNativePG rolling restart

Preferred command when the CloudNativePG kubectl plugin is installed:

```bash
kubectl cnpg restart postgresql-baseline \
  -n data-platform
```

If the plugin is not installed, apply the restart annotation used by
CloudNativePG:

```bash
kubectl annotate cluster postgresql-baseline \
  -n data-platform \
  kubectl.kubernetes.io/restartedAt="$(date -Iseconds)" \
  --overwrite
```

Watch the Pods in a separate terminal:

```bash
kubectl get pods -n data-platform -w
```

CloudNativePG should recreate the instances in a controlled sequence. Do not
delete all three Pods together, and do not delete any PVC.

### 4. Verify the recreated Pods

Wait for the Cluster:

```bash
kubectl wait cluster/postgresql-baseline \
  -n data-platform \
  --for=condition=Ready \
  --timeout=20m
```

Confirm that all Pods now report `Guaranteed`:

```bash
kubectl get pods \
  -n data-platform \
  -l cnpg.io/cluster=postgresql-baseline \
  -o custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[*].ready,QOS:.status.qosClass,NODE:.spec.nodeName
```

Confirm the Barman sidecar resources in every Pod:

```bash
kubectl get pods \
  -n data-platform \
  -l cnpg.io/cluster=postgresql-baseline \
  -o json |
jq -r '
  .items[] |
  .metadata.name as $pod |
  .status.qosClass as $qos |
  (.spec.initContainers[] |
    select(.name == "plugin-barman-cloud")) as $sidecar |
  [
    $pod,
    $qos,
    $sidecar.resources.requests.cpu,
    $sidecar.resources.limits.cpu,
    $sidecar.resources.requests.memory,
    $sidecar.resources.limits.memory
  ] | @tsv
'
```

Expected resource values:

```text
Guaranteed  500m  500m  512Mi  512Mi
```

### 5. Rerun the validation chain

```bash
./scripts/validate-cloudnative-pg-backup.sh
./scripts/validate-cloudnative-pg-persistence.sh
./scripts/validate-all.sh
```

The v0.6.4 recovery drill does not need to be rerun solely because the
sidecar-resource contract was applied to the source Pods. The recovery test
should be repeated only if backup, WAL, recovery configuration, or recovery
logic also changed.

## Lessons for Future Changes

- Treat Argo CD reconciliation and operator-managed Pod rollout as separate
  acceptance boundaries.
- After changing any ObjectStore field that affects the instance sidecar,
  verify both the ObjectStore and the generated PostgreSQL Pod specification.
- Do not assume that a Cluster reconciliation will always trigger a rollout.
- Keep disruptive restarts outside `validate-all.sh`; validation should report
  stale runtime state rather than mutate a database cluster.
- Keep the `Guaranteed` contract for the dedicated production-style database
  baseline instead of weakening the validator to accept `Burstable`.
- Report QoS and capacity-placement failures separately in future validator
  improvements so the error identifies the failed contract directly.

## References

- [CloudNativePG labels and annotations](https://cloudnative-pg.io/docs/1.30/labels_annotations/)
- [Barman Cloud Plugin instance sidecar configuration](https://cloudnative-pg.io/plugin-barman-cloud/docs/0.13.0/usage/#configuring-the-plugin-instance-sidecar)
- [Kubernetes Pod QoS classes](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/)
- [Kubernetes Guaranteed QoS requirements](https://kubernetes.io/docs/tasks/configure-pod-container/quality-service-pod/)
