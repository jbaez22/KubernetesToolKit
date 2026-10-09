# Testing Guide: Three-Tier Stack (nginx + Tomcat + Postgres)

How to stand up a realistic multi-service stack (frontend -> app server ->
database) and use it to test `k8s-toolkit diagnose-503` against a real
dependency chain, not just a single Service.

Requires: `kubectl`, `helm`, an `ingress-nginx` controller already
installed (see `KubernetesToolKit-testing-guide.md` step 1 if you don't
have one yet), and `k8s-toolkit` installed (`make setup` from the repo
root, or `.venv/bin/pip install -e .`). Everything here lives in its own
namespace, `threetier-app`, so it won't collide with the `demo-app` from
the other guide.

## 1. Add the Bitnami Helm repo (skip if already added)

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update bitnami
```

## 2. Install Postgres

```bash
helm install pg-db bitnami/postgresql \
  -n threetier-app --create-namespace \
  --set auth.postgresPassword=localtest123 \
  --set auth.username=appuser \
  --set auth.password=apppass123 \
  --set auth.database=testdb \
  --set primary.persistence.size=1Gi

kubectl wait --namespace threetier-app \
  --for=condition=ready pod -l app.kubernetes.io/instance=pg-db \
  --timeout=120s
```

Credentials are intentionally fixed (not auto-generated) so you can log in:
user `appuser` / password `apppass123` / db `testdb`. Local test cluster
only -- don't reuse these anywhere real.

## 3. Install Tomcat

Tomcat's pods wait on Postgres via a real init container (`pg_isready`),
so a DB outage produces a real, Kubernetes-visible failure chain -- not
just a synthetic check.

```bash
helm install tomcat-app bitnami/tomcat \
  -n threetier-app -f testing/sample-app/tomcat-values.yaml

kubectl wait --namespace threetier-app \
  --for=condition=ready pod -l app.kubernetes.io/instance=tomcat-app \
  --timeout=120s
```

## 4. Deploy the frontend and Ingress

```bash
kubectl apply -f testing/sample-app/threetier-frontend.yaml

kubectl wait --namespace threetier-app \
  --for=condition=ready pod -l app=frontend --timeout=60s
```

## 5. Confirm it's healthy end to end

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 18080:80 &

curl -H "Host: threetier-app.local" http://127.0.0.1:18080/healthz
# expect: 200 (frontend's own health, independent of the backend)

curl -H "Host: threetier-app.local" http://127.0.0.1:18080/
# expect: 404 -- this is normal, this Tomcat image ships no default
# webapp. A 404 means the request made it all the way to Tomcat.
```

To browse in an actual browser: add `127.0.0.1 threetier-app.local` to
`/etc/hosts`, then open `http://threetier-app.local:18080/`.

## 6. Log in to Postgres and run queries

No local `psql` needed -- this runs a disposable client pod:

```bash
kubectl run pg-client --rm --tty -i --restart=Never --namespace threetier-app \
  --image docker.io/bitnami/postgresql:latest --env="PGPASSWORD=apppass123" \
  --command -- psql --host pg-db-postgresql -U appuser -d testdb -p 5432
```

A sample table is already there to try:
```sql
SELECT * FROM items;
```

## 7. Run the diagnostic tool

Check all three tiers in one run (comma-separated Service names) -- this
is the one you want, since a single-Service run only ever sees that one
tier and will stay silent about a broken Tomcat or Postgres:
```bash
.venv/bin/k8s-toolkit diagnose-503 -n threetier-app -s frontend,tomcat-app,pg-db-postgresql -i frontend -o ./testing/reports
```
Ends with a summary line per Service so you can see at a glance which
tier is broken. Each Service still gets its own full report above that.

To check just one tier on its own:
```bash
.venv/bin/k8s-toolkit diagnose-503 -n threetier-app -s tomcat-app -o ./testing/reports
```

## 8. Break it on purpose, then re-run the tool

### Scenario A -- Frontend scaled to zero

```bash
# break
kubectl scale deployment frontend -n threetier-app --replicas=0

# fix
kubectl scale deployment frontend -n threetier-app --replicas=2
```
Run the step 7 multi-service command. Expect the summary to show
`[FAIL] frontend` (`Pods: FAIL`, `Service endpoints: FAIL`), with
`tomcat-app` and `pg-db-postgresql` still `[OK]`. `curl` through the
Ingress returns `503`.

### Scenario B -- Tomcat scaled to zero (frontend still up)

```bash
# break
kubectl scale deployment tomcat-app -n threetier-app --replicas=0

# fix
kubectl scale deployment tomcat-app -n threetier-app --replicas=2
```
Run the step 7 multi-service command. Expect the summary to show
`[FAIL] tomcat-app` (`Pods: FAIL`, `Service endpoints: FAIL`), with
`frontend` still `[OK]`. But `curl` through the Ingress now returns
`502`, not `503` -- the frontend itself is healthy and reachable, it's
nginx's own "upstream unreachable" response. This is exactly why checking
every tier in one run matters: a single-Service check against `frontend`
alone would have reported everything healthy.

### Scenario C -- Database outage while Tomcat restarts

```bash
# break
kubectl scale statefulset pg-db-postgresql -n threetier-app --replicas=0
kubectl delete pod -n threetier-app -l app.kubernetes.io/instance=tomcat-app

# fix
kubectl scale statefulset pg-db-postgresql -n threetier-app --replicas=1
```
New Tomcat pods get stuck in `Init` (the `wait-for-postgres` init
container keeps retrying, so the Pod phase stays `Pending`). Run the
step 7 multi-service command. Expect `[FAIL] tomcat-app` -- `Pod
readiness: FAIL` and a `Pod state: ... Pod phase is Pending` FAIL. Pods
recover on their own a few seconds after the "fix" command, once
Postgres is back.

## 9. Clean up

```bash
kill %1   # stops the port-forward from step 5

kubectl delete -f testing/sample-app/threetier-frontend.yaml
helm uninstall tomcat-app -n threetier-app
helm uninstall pg-db -n threetier-app
kubectl delete namespace threetier-app
```
