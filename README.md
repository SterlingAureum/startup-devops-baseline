# startup-devops-baseline

A local-first DevOps, GitOps, progressive delivery, and AWS EKS infrastructure baseline for early-stage teams.

This repository demonstrates a practical Kubernetes platform baseline built around kind, Argo CD, Helm, ingress-nginx, Argo Rollouts, GHCR image publishing, Prometheus, and a small demo API service.

The repository now contains the completed local progressive-delivery and AWS
EKS baselines, isolated On-Demand and Spot application NodePools, a tag-scoped
AWS FIS drill, and a GitOps-managed CloudNativePG PostgreSQL persistence,
high-availability, S3 backup, point-in-time recovery, application integration,
and primary-failover baseline. Reusable CI quality gates protect both
pull-request validation and GHCR image publishing. Published application
images now carry a SHA tag, immutable OCI digest, structured source identity,
and GitHub build-provenance attestation. Successful main-branch builds now
turn that identity into a reviewable aws-dev GitOps promotion pull request.
Promoted values and live workloads now retain enough delivery metadata to
correlate source, build, Git promotion, Argo CD reconciliation, Pod image ID,
and the application-reported version. The repository remains intentionally
smaller than a full production platform and will continue toward Git rollback,
security controls, observability, AI infrastructure workloads, and AIOps
workflows.

## Current Version

```text
v0.7.3-delivery-traceability
```
The Promotion PR now stores the full source commit and workflow run ID beside
the image tag and digest. Helm projects that identity into Deployment and Pod
annotations, while `validate-demo-api-delivery-trace.sh` proves that the
promotion commit, Argo CD revision, live Pod image ID, and `/version` response
all identify the same release. Human review and Argo CD remain the environment
promotion and deployment boundaries.

## Platform Architecture

```text
                         GitHub Repository

                                  |
                                  v

                               Argo CD

                         GitOps Control Plane

                                  |
                                  v

                      Kubernetes Applications

                                  |
                                  v

                         Application Delivery

                    - Helm
                    - Argo Rollouts


                                  |
                                  v

                          demo-api Workload



                 +----------------+----------------+

                 |                                 |

                 v                                 v


        Local Kubernetes Environment       AWS Kubernetes Environment


                 kind                         Amazon EKS


                  |                               |


          ingress-nginx              AWS Load Balancer
                                     Controller


                  |                               |


          Local Ingress                     AWS ALB
```

Both environments use Git and Argo CD as the desired-state control plane.
The local environment focuses on progressive delivery, while the AWS
environment covers cloud infrastructure, AWS-native application delivery,
dynamic capacity, and the CloudNativePG database control plane.

## Deployment Options

### Local GitOps Environment

Use the local environment for fast iteration, GitOps validation, and
progressive-delivery experiments.

See `docs/LOCAL_DEPLOYMENT.md`.

### AWS EKS Environment

Use the AWS environment for Terraform-managed infrastructure, Amazon EKS,
Argo CD bootstrap, AWS-native ingress, and cloud validation.

See `docs/AWS_EKS_DEPLOYMENT.md`.

## Repository Structure

```text
startup-devops-baseline/
├── .github/
│   └── workflows/
├── apps/
│   └── demo-api/
├── clusters/
│   ├── local/
│   └── aws-dev/
├── infra/
│   └── terraform/aws/
├── docs/
├── examples/
├── platform/
└── scripts/
```

## Documentation

### Architecture

- `docs/ARCHITECTURE.md`
- `docs/AWS_EKS_ARCHITECTURE.md`
- `docs/ENVIRONMENT_MODEL.md`

### Deployment and Operations

- `docs/LOCAL_DEPLOYMENT.md`
- `docs/AWS_EKS_DEPLOYMENT.md`
- `docs/AWS_EKS_DESTROY_RUNBOOK.md`
- `docs/TROUBLESHOOTING.md`

### GitOps and Delivery

- `docs/CI_IMAGE_WORKFLOW.md`
- `docs/DELIVERY_TRACEABILITY.md`
- `docs/GITOPS_WORKFLOW.md`
- `docs/GHCR_IMAGE_WORKFLOW.md`
- `docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md`

### Terraform

- `docs/TERRAFORM_OUTPUTS.md`
- `docs/TERRAFORM_STATE_MANAGEMENT.md`

### Project Evolution

- `CHANGELOG.md`
- `docs/ROADMAP.md`
