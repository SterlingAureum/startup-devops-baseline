# Local Platform App-of-Apps Chart

This Helm Chart is the source path of `Application/startup-devops-root`. It
renders the five local child Applications.

`git.targetRevision` applies only to child Applications that read this Git
repository: `namespace-guardrails` and `demo-api`. The Root source revision is
rendered by `scripts/deploy-root-app.sh` from the same value during feature
acceptance.

External Helm sources remain independently pinned in `values.yaml`:

- Argo Rollouts `2.41.0`;
- ingress-nginx `4.11.3`;
- kube-prometheus-stack `88.5.0`.

Stable values use `HEAD` and render `demo-api` Helm parameters as an explicit
empty list. Feature mode is supplied only through the Root Application and
renders the exact four local-image parameters. Do not commit a feature branch
or feature SHA into this Chart.
