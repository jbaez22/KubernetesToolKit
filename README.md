# KubernetesToolKit

A growing collection of tools to monitor, diagnose, troubleshoot, and
eventually auto-correct issues in Kubernetes clusters and the
applications running on them, packaged as a single `k8s-toolkit` CLI.

## Installation

Requires Python 3.9+ and `kubectl` with a valid kubeconfig/context
pointed at the target cluster.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

This installs the `k8s-toolkit` command into `.venv/bin/`.

## Tools

### `diagnose-503`

Read-only diagnostic tool for identifying common causes of HTTP 503
errors in a Kubernetes application exposed via a Service (and optionally
an Ingress).

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

**Flags:**
- `-n` - Namespace the Service(s) live in
- `-s` - Service name to diagnose. Comma-separated list to check every
  tier of a multi-service app (e.g. frontend, app server, database) in
  one run
- `-i` - Ingress name to check (optional). Only checked against the
  first Service when `-s` has more than one
- `-o` - Directory for JSON reports. Default: `./reports`

**Usage:**

```bash
k8s-toolkit diagnose-503 -n <Namespace> -s <ServiceName> -i <IngressName>
```

Example (single Service):

```bash
k8s-toolkit diagnose-503 -n production -s payments-api

k8s-toolkit diagnose-503 \
    -n production \
    -s payments-api \
    -i payments-ingress
```

Example (full application stack, one tier failing won't hide behind the
others):

```bash
k8s-toolkit diagnose-503 -n threetier-app -s frontend,tomcat-app,pg-db-postgresql -i frontend
```

**Output:**
- Human-readable diagnostic report on stdout
- JSON report written to `./reports` (configurable via `-o`)

This tool is strictly read-only — it never modifies cluster state.

**Example Output:**

Checking a Postgres Service with zero matching Pods (a real captured run):

![Example terminal output](Report-Example1.png)

Each run also writes a JSON report with the same data — see
[`Report-Example1.json`](Report-Example1.json) for the file behind the
screenshot above.

## Development

```bash
make setup   # create .venv, install dev tooling + the package itself
make check   # lint, type-check, test (>=80% coverage), dependency audit
```

See `Makefile` for the individual targets (`lint`, `typecheck`, `test`,
`audit`).

## Project structure

```text
src/k8s_toolkit/
├── cli.py                 # k8s-toolkit entry point, one subcommand per tool
├── kubernetes_client.py    # thin, tested kubectl wrapper
├── models.py                # shared CheckResult/DiagnosticReport
├── checks/
│   └── http_503.py         # diagnose-503 logic
└── reporting/
    ├── console.py           # human-readable terminal output
    └── json_report.py       # JSON report file output
tests/                      # pytest, kubectl fully mocked -- no cluster needed
```

## Roadmap

Planned additions as the toolkit grows:
- Monitoring helpers (metrics/log aggregation checks)
- General troubleshooting scripts for other common failure modes
  (CrashLoopBackOff, OOMKilled, scheduling failures, network policy denials)
- Opt-in remediation scripts for well-understood, low-risk fixes

## License

MIT - see [LICENSE](LICENSE).
