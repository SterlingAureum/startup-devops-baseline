# Rollback

Rollback is implemented for the local progressive-delivery baseline.

Use `docs/ROLLBACK_RUNBOOK.md` for the current operator workflow, including:

- aborting an active canary rollout;
- promoting a healthy rollout;
- reverting a GitOps image change;
- validating the stable revision after recovery.

For the AWS environment, revert the Git commit and allow Argo CD to reconcile
the previous desired state. Database-specific rollback, restore, and
point-in-time recovery procedures will be added with the PostgreSQL resources
in later v0.6 increments.
