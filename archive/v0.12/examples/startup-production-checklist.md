# Startup Production Checklist

This checklist is a lightweight guide for evolving the local v0.1 baseline toward a more production-like startup platform.

It is not a compliance checklist. It is a practical engineering checklist.

## Platform

- Kubernetes cluster lifecycle is automated.
- Cluster version is pinned and upgrade process is documented.
- Platform components are managed by GitOps.
- Application workloads are separated from platform components.
- Environments are clearly separated.

## Deployment

- Application deployment is managed by Argo CD.
- Helm chart values are environment-specific.
- Rollback process is documented.
- Image tag strategy is defined.
- Manual kubectl changes are avoided for normal deployment.

## CI/CD

- Docker image build is automated.
- Image tags are traceable to commits.
- Helm templates are validated in CI.
- Basic vulnerability scanning is enabled.
- Failed builds block deployment updates.

## Ingress and Traffic

- Ingress controller is managed by GitOps.
- Application routes are documented.
- TLS strategy is defined for non-local environments.
- Health and readiness checks are exposed.

## Observability

- Application exposes metrics.
- Prometheus scrapes application metrics.
- Basic dashboards are planned or available.
- Alerting strategy is defined before production use.
- Runbooks exist for common failures.

## Security

- Secrets are not committed to Git.
- Local secret examples use `.example` files only.
- Kubernetes RBAC is reviewed.
- Container images are scanned.
- Public access paths are intentional and documented.

## Data

- Databases are not added to Kubernetes without a backup and restore strategy.
- Persistent storage class is documented.
- Backup restore has been tested.
- Database upgrades have a rollback plan.

## Cost

- Local baseline has no cloud cost.
- Cloud version should document estimated AWS cost.
- Autoscaling policies should avoid idle waste.
- Spot usage should be explicitly planned and tested.

## AI Infrastructure Extension

- GPU node scheduling is isolated from normal workloads.
- Model-serving workloads have resource requests and limits.
- Model artifacts and image sizes are documented.
- Inference metrics are exposed.
- Cost and capacity planning are documented.

## AIOps Extension

- Alerts are structured and actionable.
- Incident summaries are generated from reliable inputs.
- Human approval is required before automated remediation.
- Runbooks are version-controlled.
