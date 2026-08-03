# TLS and DNS module

This module discovers an existing public Route 53 hosted zone and creates a
DNS-validated ACM certificate for one demo hostname. Terraform owns the ACM
certificate and its validation records.

The Kubernetes Ingress creates the ALB later in the deployment sequence, so
the public Alias record is reconciled by
`scripts/reconcile-demo-api-dns.sh` after the ALB hostname exists. That script
is idempotent and never stores a workstation public IP in the repository.
