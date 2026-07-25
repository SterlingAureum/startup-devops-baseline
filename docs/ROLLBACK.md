# Rollback

Rollback is implemented for the local progressive-delivery baseline.

Use `docs/ROLLBACK_RUNBOOK.md` for the current operator workflow, including:

- aborting an active canary rollout;
- promoting a healthy rollout;
- reverting a GitOps image change;
- validating the stable revision after recovery.

For the AWS environment, revert the Git commit and allow Argo CD to reconcile
the previous desired state.

For the v0.6.1 database baseline, Git rollback can reconcile non-destructive
configuration changes but is not a data restore mechanism. Automated prune is
disabled for the database Application, and the stateful resources carry
`Prune=false`; do not delete the Cluster or PVC to roll back an application
change. Backup, restore, and point-in-time recovery are deferred to later v0.6
increments.
