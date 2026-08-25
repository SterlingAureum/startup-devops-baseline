# PostgreSQLCollectionFailed

## Meaning

A CloudNativePG instance collector reported collection errors continuously for
5 minutes. The signal is AWS-profile-only and remains no-data in the local
profile by design.

## Impact

Database health visibility is degraded and database-backed application
diagnosis may be incomplete. The alert does not by itself prove database
unavailability.

## First response

```bash
kubectl -n data-platform get cluster,pods,svc -o wide
kubectl -n data-platform describe cluster postgresql-baseline
kubectl -n data-platform logs -l cnpg.io/cluster=postgresql-baseline --since=15m --tail=200
kubectl -n cnpg-system get pods
```

Query `data:postgresql_collection_errors:max`,
`data:postgresql_instances_up:min`, and the CloudNativePG Prometheus target.
Correlate the result with demo-api dependency telemetry. Do not print Secret
contents or database credentials.

## Diagnosis and recovery

- Distinguish exporter collection failure from PostgreSQL instance failure and
  from Prometheus scrape failure.
- Inspect operator reconciliation, instance readiness, certificates, Service
  endpoints, and NetworkPolicy.
- Do not delete Pods, PVCs, backups, or the Cluster resource.
- Switchover, restore, credential rotation, or storage changes require the
  reviewed database recovery procedure and environment approval.

Resolve when collection errors remain zero, all expected instance metrics and
targets are healthy, and demo-api dependency checks recover. Record the cluster,
instance, cause, and recovery evidence.
