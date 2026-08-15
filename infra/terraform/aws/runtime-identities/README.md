# Persistent GitHub Runtime Identities

This account-bootstrap Terraform root owns the `aws-dev-runtime` and
`aws-test-runtime` GitHub OIDC IAM roles independently from disposable EKS
environment state.

Apply it before the clean-room `environment_absent` checkpoint. The roles can
identify the caller and describe only their exact deterministic cluster ARN.
When the cluster does not exist, AWS returns `ResourceNotFoundException`, which
the runtime collector records as `blocked / environment_absent`.

The dev/test environment roots own only the matching EKS access entries. Do
not destroy this root as part of ordinary dev/test cleanup. It creates no EKS,
EC2, VPC, NAT, load balancer, or Kubernetes resource.
