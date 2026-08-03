# External Secrets AWS Foundation Module

Creates the AWS-side foundation for External Secrets Operator:

- one Secrets Manager Secret container for the demo-api PostgreSQL connection;
- one IRSA role trusted only by the
  `external-secrets/external-secrets` ServiceAccount; and
- one IAM policy that grants `DescribeSecret` and `GetSecretValue` only for
  that Secret ARN.

The module deliberately does not create an `aws_secretsmanager_secret_version`.
Secret values must be written through the explicit migration workflow added in
a later checkpoint, so credentials never enter Git or Terraform state.

`recovery_window_in_days` defaults to `0` for repeatable teardown of the
disposable aws-dev environment. Persistent environments should use a value
from `7` through `30` and manage the Secret lifecycle independently from the
EKS cluster.
