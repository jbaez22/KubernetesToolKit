# KubernetesToolKit

A growing collection of tools and scripts to monitor, diagnose, troubleshoot,
and eventually auto-correct issues in Kubernetes clusters and the
applications running on them.

## Tools

### `k8s_503_diagnose.py`

Read-only diagnostic tool for identifying common causes of HTTP 503 errors
in a Kubernetes application exposed via a Service (and optionally an
Ingress).

**Checks performed:**
- Service existence and selector validity
- Pod readiness and phase (including init containers)
- Container waiting/terminated states and restart counts
- Service endpoints, including not-ready endpoints
- Service `targetPort` vs. container port (numeric and named ports)
- Readiness/liveness probe configuration
- Recent Kubernetes warning events scoped to the affected Service/Pods
- Ingress backend routing (if an Ingress name is supplied)
- Pod CPU/memory metrics (if `metrics-server` is installed)

**Requirements:**
- Python 3.9+
- `kubectl`, with a valid kubeconfig/context pointed at the target cluster
- Optional: `metrics-server` for CPU/memory checks

**Usage:**

```bash
python3 k8s_503_diagnose.py -n production -s payments-api

python3 k8s_503_diagnose.py \
    -n production \
    -s payments-api \
    -i payments-ingress
```

**Output:**
- Human-readable diagnostic report on stdout
- JSON report written to `./reports` (configurable via `-o`)

This tool is strictly read-only — it never modifies cluster state.

## Roadmap

Planned additions as the toolkit grows:
- Monitoring helpers (metrics/log aggregation checks)
- General troubleshooting scripts for other common failure modes
  (CrashLoopBackOff, OOMKilled, scheduling failures, network policy denials)
- Opt-in remediation scripts for well-understood, low-risk fixes

## License

MIT - see [LICENSE](LICENSE).
