# Testing Guide: `k8s-toolkit diagnose-503`

How to stand up a disposable test app and use it to verify the diagnostic
tool works, including recreating real 503 scenarios.

Requires: `kubectl` pointed at a test cluster (Docker Desktop Kubernetes,
kind, or minikube), the cluster not already using port `18080` locally,
and `k8s-toolkit` installed (`make setup` from the repo root, or
`.venv/bin/pip install -e .`).

## 1. Install an Ingress controller (skip if one already exists)

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/cloud/deploy.yaml

kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

## 2. Deploy the demo app

```bash
kubectl apply -f testing/sample-app/demo-app.yaml

kubectl wait --namespace demo-app \
  --for=condition=ready pod \
  --selector=app=demo-app \
  --timeout=90s
```

## 3. Open a tunnel to the app and confirm it's healthy

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 18080:80 &

curl -H "Host: demo-app.local" http://127.0.0.1:18080/
# expect: HTTP 200
```

Check if the port-forward was already started:

```bash
lsof -nP -iTCP:18080 -sTCP:LISTEN
ps aux | grep "kubectl port-forward" | grep -v grep
lsof -iTCP -sTCP:LISTEN | grep -E "com.docke|kubectl"
kubectl get svc --all-namespaces
```

## 4. Run the diagnostic tool against the healthy app

```bash
.venv/bin/k8s-toolkit diagnose-503 -n demo-app -s demo-app -i demo-app -o ./testing/reports
```

Expect all checks to be `PASS` (events may show a one-time `WARN` the first
time you run this, from the controller/app still starting up — safe to ignore).

## 5. Break it on purpose, then re-run the tool

Each scenario below: run the "break" command, re-run the tool (step 4),
confirm `curl` returns a `503`, then run the "fix" command to restore it
before moving to the next scenario.

### Scenario A — Service port name typo

```bash
# break
kubectl patch service demo-app -n demo-app --type=json \
  -p='[{"op":"replace","path":"/spec/ports/0/targetPort","value":"https"}]'

# fix
kubectl patch service demo-app -n demo-app --type=json \
  -p='[{"op":"replace","path":"/spec/ports/0/targetPort","value":"http"}]'
```
The tool should flag: `Service endpoints: FAIL` and `Service targetPort: WARN`.

### Scenario B — Service selector doesn't match any Pods

```bash
# break
kubectl patch service demo-app -n demo-app --type=json \
  -p='[{"op":"replace","path":"/spec/selector","value":{"app":"demo-app-wrong"}}]'

# fix
kubectl patch service demo-app -n demo-app --type=json \
  -p='[{"op":"replace","path":"/spec/selector","value":{"app":"demo-app"}}]'
```
The tool should flag: `Pods: FAIL` ("No Pods match the Service selector")
and `Service endpoints: FAIL`.

### Scenario C — Readiness probe pointed at the wrong port

```bash
# break
kubectl patch deployment demo-app -n demo-app --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/port","value":8888}]'

# fix
kubectl rollout undo deployment/demo-app -n demo-app
```
The tool should flag: `Pod readiness: WARN` and `Not-ready endpoints: WARN`.
(The app may stay up during this one — the old, healthy Pods are still
serving traffic while the broken replica rolls out.)

## 6. Clean up

```bash
kill %1   # stops the port-forward from step 3

kubectl delete -f testing/sample-app/demo-app.yaml
kubectl delete namespace ingress-nginx
```
