# Local Platform App-of-Apps Chart

This Helm Chart is the source path of `Application/startup-devops-root`. It
renders the six local child Applications.

`git.targetRevision` applies only to child Applications that read this Git
repository: `namespace-guardrails`, `demo-api`, and `observability-views`. The Root source revision is
rendered by `scripts/deploy-root-app.sh` from the same value during feature
acceptance.

External Helm sources remain independently pinned in `values.yaml`:

- Argo Rollouts `2.41.1`;
- ingress-nginx `4.11.3`;
- kube-prometheus-stack `88.5.0`.

The monitoring Application enables private single-replica Prometheus,
Grafana, and Alertmanager runtimes for local functional acceptance. Alert rules
remain repository-owned by `platform/observability/helm` and are intentionally
absent until v0.11.5.1.

The repository-owned `observability-views` Chart is not an external dependency;
it inherits `git.targetRevision` from the Root and deploys recording rules,
controller ServiceMonitors, and Dashboard ConfigMaps after the monitoring
control plane. CloudNativePG PodMonitors remain disabled in the local profile.

Stable values use `HEAD` and render `demo-api` Helm parameters as an explicit
empty list. Feature mode is supplied only through the Root Application and
renders the exact four local-image parameters. Do not commit a feature branch
or feature SHA into this Chart.
