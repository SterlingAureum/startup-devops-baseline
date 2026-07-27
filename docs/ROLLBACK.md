# Rollback

Rollback is implemented for the local progressive-delivery baseline.

Use `docs/ROLLBACK_RUNBOOK.md` for the current operator workflow, including:

- aborting an active canary rollout;
- promoting a healthy rollout;
- reverting a GitOps image change;
- validating the stable revision after recovery.

For the AWS environment, revert the Git commit and allow Argo CD to reconcile
the previous desired state.

For the v0.6.5 database baseline, Git rollback can reconcile non-destructive
configuration changes but is not a data restore mechanism. Automated prune is
disabled for the database Application, and the stateful resources carry
`Prune=false`; do not delete the Cluster or PVC to roll back an application
change. Reducing `instances` removes a database instance and its PVC, so do not
roll back from three instances to one without an explicit data and capacity
plan. Latest-state restore and point-in-time recovery are validated only by
bootstrapping separate recovery Clusters; they do not overwrite the source
Cluster. Do not remove the Barman plugin, ObjectStore, shared ServiceAccount
annotation, backup IAM role, or archived recovery window while a restore is
running. Treat the guarded recovery script as a disaster-recovery test, not as
a substitute for reverting an application manifest.

To roll back demo-api, restore the previous immutable image tag and Helm values
through Git. Do not roll back by deleting the PostgreSQL Cluster, generated
application Secret, or PVCs. `startup-apps/demo-api-postgresql` is runtime state
outside Git; when database integration remains enabled, refresh it with
`scripts/sync-demo-api-postgresql-secret.sh`. If database integration is
intentionally disabled, first deploy values with `database.enabled=false`, then
remove the runtime Secret.
