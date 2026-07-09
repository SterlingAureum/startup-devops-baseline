# Ingress

The v0.1 baseline uses ingress-nginx to expose the demo API through local HTTP ingress.

## Components

```text
ingress-nginx namespace
  |
  +-- ingress-nginx-controller

startup-apps namespace
  |
  +-- demo-api Service
  +-- demo-api Ingress
```

## Hostname

The demo API uses:

```text
demo-api.local
```

## Access Without /etc/hosts

Use the Host header directly:

```bash
curl -H "Host: demo-api.local" http://localhost/health
curl -H "Host: demo-api.local" http://localhost/ready
curl -H "Host: demo-api.local" http://localhost/version
```

## Access With /etc/hosts

Add the local hostname:

```bash
echo "127.0.0.1 demo-api.local" | sudo tee -a /etc/hosts
```

Then test:

```bash
curl http://demo-api.local/health
curl http://demo-api.local/ready
curl http://demo-api.local/version
```

## Check Ingress Resources

```bash
kubectl get application ingress-nginx -n argocd
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
kubectl get ingress -n startup-apps
kubectl get ingress -n startup-apps demo-api -o yaml
```

Expected ingress rule:

```text
host: demo-api.local
path: /
backend service: demo-api:80
```

## Check kind Port Mapping

The kind control-plane container should expose local ports 80 and 443:

```bash
docker ps | grep startup-devops-baseline-control-plane
```

Expected ports include:

```text
0.0.0.0:80->80/tcp
0.0.0.0:443->443/tcp
```

## Scripted Check

Run:

```bash
./scripts/check-ingress.sh
```

This checks the ingress controller rollout, demo-api ingress resource, and HTTP access through ingress.

## Common Issues

### Port 80 Is Already Used

If another local service is already using port 80, kind may fail to create the expected port mapping.

Check:

```bash
sudo ss -ltnp | grep ':80'
```

Stop the conflicting service or change the kind port mapping.

### Hostname Does Not Resolve

Use the Host header approach first:

```bash
curl -H "Host: demo-api.local" http://localhost/health
```

If that works, add `/etc/hosts` for direct hostname access.

### Ingress Exists but Requests Fail

Check:

```bash
kubectl get pods -n ingress-nginx
kubectl logs -n ingress-nginx deploy/ingress-nginx-controller --tail=100
kubectl get endpoints -n startup-apps demo-api
```
