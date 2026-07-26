# CloudNativePG Backup Module

Creates the development S3 backup bucket and the least-privilege IRSA role used
by the `data-platform/postgresql-baseline` ServiceAccount.

The bucket blocks public access, requires TLS, enables versioning, and uses
Amazon S3 managed encryption. `force_destroy` defaults to `true` for the
disposable aws-dev environment; production environments should preserve backup
storage independently from the EKS lifecycle.
