# AWS operator lifecycle transition

The five Terraform roots, their backend examples, modules and AWS GitOps
environment declarations retain their paths and resource configuration in this
increment. No state migration, backend key change or AWS action is performed.

Current static entrypoints:

```bash
bash scripts/checks/terraform.sh
python3 scripts/delivery/flow.py render --environment aws-dev
python3 scripts/delivery/flow.py render --environment aws-test
python3 scripts/delivery/flow.py render --environment aws-prod
python3 scripts/delivery/flow.py platform
```

Terraform validation needs Terraform and provider download access; app rendering
needs Helm; platform rendering also needs kubectl. These checks do not apply
resources or prove that external controller chart combinations work live.

Legacy apply/bootstrap/destroy/recovery/cost-audit scripts have moved together
to `archive/v0.12/scripts/`. They depend on historical executor, state-location,
approval and relative-path assumptions. They are not current commands and must
not be run from the relocated directory. Historical materials remain available
without being made a dependency of current CI.

Next work is the new environment-scoped dev/test operator chain: identify the
account and target, plan/apply reviewed infrastructure, bootstrap GitOps,
verify runtime behavior, prepare and execute destruction, and inspect residual
resources. Retained state-backend resources and backup-data policy remain
separate from disposable environment deletion.

Current cloud release/runtime workflows are optional adapters for already
provisioned clusters and existing trusted runners. They do not create a
cluster or replace the pending AWS operator chain. Keep publication, runtime
and production disabled until their prerequisites and rehearsal are complete.
