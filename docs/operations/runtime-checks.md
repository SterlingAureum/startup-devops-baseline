# Runtime checks remain separate from lifecycle

The lifecycle verify result means environment and GitOps delivery convergence.
Application behavior and continuous monitoring are separate responsibilities.

| Scope | Owner / entrypoint |
| --- | --- |
| Nodes, Argo controllers, declared Application convergence | `scripts/ops/cli.py verify` |
| Demo-api local-source Rollout/Pods, HTTP identity and exposed metric | Optional `scripts/examples/demo_api.py verify` |
| Existing AWS demo release acceptance and promotion | Existing optional `scripts/delivery/runtime.py` workflows |
| Continuous metrics/logs/traces and alerts | Platform observability declarations and their backends |
| Future custom application smoke tests | Application-owned test script or Kubernetes Job |

A custom application can be declared as another child Application in the root
chart. Lifecycle checks discover its identity from rendering and use Argo status;
they do not require demo-api labels, a Rollout, a particular Service or HTTP path.
CI remains responsible for the repository's configured build/render checks;
adding a new app does not automatically add its business tests to current CI.

Application smoke tests may later run independently, as a Kubernetes Job managed
by the application's delivery configuration, or as an explicit post-deployment CI
step. Lifecycle orchestration can consume their exit/result without absorbing
their probe configuration. No arbitrary executable hook/plugin mechanism or new
continuous runtime detection platform is introduced by this increment.

The optional demo verifier checks exposed metrics through the Service proxy;
it does not prove Prometheus, Loki or Tempo ingestion. Its generation/replica
counters accept nonnegative integers or decimal strings while rejecting nulls,
booleans, negative/fractional or malformed values. It does not auto-promote a
paused Rollout. The previous counter hotfix remains in that example adapter.
