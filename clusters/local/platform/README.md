# Local Platform Applications

This directory is the target path for the Argo CD root application.

The root application is defined in:

```text
clusters/local/root-app.yaml
```

Future batches will add child Argo CD application manifests here, such as:

- ingress-nginx
- monitoring
- demo-api

The directory is intentionally lightweight in the current batch so that the kind + Argo CD control-plane loop can be validated before deploying additional workloads.
