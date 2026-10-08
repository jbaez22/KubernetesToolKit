#!/usr/bin/env python3

"""
Kubernetes 503 Diagnostic Tool

Read-only troubleshooting tool for identifying common causes of
HTTP 503 errors in Kubernetes applications.

Requirements:
    - Python 3.9+
    - kubectl
    - Valid kubeconfig/context
    - Optional: metrics-server for CPU/memory checks

Example:
    python3 k8s_503_diagnose.py -n production -s payments-api

    python3 k8s_503_diagnose.py \
        -n production \
        -s payments-api \
        -i payments-ingress

Output:
    - Human-readable diagnostic report on stdout
    - JSON report written to the current directory
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    status: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    timestamp: str
    context: str
    namespace: str
    service: str
    ingress: Optional[str]
    components: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Kubernetes command wrapper
# ---------------------------------------------------------------------------

class KubectlError(Exception):
    """Raised when kubectl cannot execute successfully."""


class KubernetesClient:
    """Small wrapper around kubectl."""

    def __init__(self, namespace: str):
        self.namespace = namespace

    def run(
        self,
        args: list[str],
        *,
        json_output: bool = False,
        allow_failure: bool = False,
    ) -> Any:

        command = ["kubectl", *args, "-n", self.namespace]

        if json_output:
            command.extend(["-o", "json"])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise KubectlError(
                "kubectl was not found. Please install kubectl."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise KubectlError(
                f"kubectl command timed out: {' '.join(command)}"
            ) from exc

        if result.returncode != 0:
            if allow_failure:
                return None

            error = result.stderr.strip() or result.stdout.strip()

            raise KubectlError(
                f"kubectl command failed: {' '.join(command)}\n{error}"
            )

        if json_output:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise KubectlError(
                    f"kubectl returned invalid JSON: {exc}"
                ) from exc

        return result.stdout.strip()

    def get_context(self) -> str:
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

        if result.returncode != 0:
            return "unknown"

        return result.stdout.strip()


# ---------------------------------------------------------------------------
# Diagnostic engine
# ---------------------------------------------------------------------------

class Kubernetes503Diagnoser:

    def __init__(
        self,
        client: KubernetesClient,
        service_name: str,
        ingress_name: Optional[str] = None,
    ):
        self.client = client
        self.service_name = service_name
        self.ingress_name = ingress_name

        self.report = DiagnosticReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            context=client.get_context(),
            namespace=client.namespace,
            service=service_name,
            ingress=ingress_name,
        )

        self.service: Optional[dict[str, Any]] = None
        self.pods: list[dict[str, Any]] = []
        self.endpoints: Optional[dict[str, Any]] = None
        self.ingress: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def add_check(
        self,
        name: str,
        status: str,
        message: str,
        details: Optional[list[str]] = None,
    ) -> None:

        self.report.checks.append(
            CheckResult(
                name=name,
                status=status,
                message=message,
                details=details or [],
            )
        )

    def add_finding(self, message: str) -> None:
        if message not in self.report.findings:
            self.report.findings.append(message)

    def add_recommendation(self, message: str) -> None:
        if message not in self.report.recommendations:
            self.report.recommendations.append(message)

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------

    def check_service(self) -> bool:

        service = self.client.run(
            ["get", "service", self.service_name],
            json_output=True,
            allow_failure=True,
        )

        if not service:
            self.add_check(
                "Service",
                "FAIL",
                f"Service '{self.service_name}' was not found.",
            )

            self.add_finding(
                "The requested Kubernetes Service does not exist."
            )

            self.add_recommendation(
                f"Verify the Service name and namespace: "
                f"kubectl get svc -n {self.client.namespace}"
            )

            return False

        self.service = service

        selector = service.get("spec", {}).get("selector", {})

        ports = service.get("spec", {}).get("ports", [])

        port_details = [
            f"{p.get('port')} -> {p.get('targetPort')}"
            for p in ports
        ]

        self.add_check(
            "Service",
            "PASS",
            f"Service '{self.service_name}' exists.",
            [
                f"Selector: {selector}",
                f"Ports: {', '.join(port_details)}",
            ],
        )

        if not selector:
            self.add_check(
                "Service selector",
                "WARN",
                "Service does not have a selector.",
            )

            self.add_finding(
                "Service has no selector. It may rely on manually "
                "managed EndpointSlices."
            )

        return True

    # ------------------------------------------------------------------
    # Pods
    # ------------------------------------------------------------------

    def check_pods(self) -> None:

        if not self.service:
            return

        selector = self.service.get("spec", {}).get("selector", {})

        if not selector:
            return

        selector_string = ",".join(
            f"{key}={value}"
            for key, value in selector.items()
        )

        pods = self.client.run(
            [
                "get",
                "pods",
                "-l",
                selector_string,
            ],
            json_output=True,
            allow_failure=True,
        )

        if not pods:
            self.add_check(
                "Pods",
                "FAIL",
                "No Pods were found matching the Service selector.",
            )

            self.add_finding(
                "The Service selector does not currently match any Pods."
            )

            self.add_recommendation(
                "Compare Pod labels against the Service selector: "
                f"kubectl get pods -n {self.client.namespace} --show-labels"
            )

            return

        self.pods = pods.get("items", [])

        if not self.pods:
            self.add_check(
                "Pods",
                "FAIL",
                "No Pods match the Service selector.",
            )
            return

        ready_count = 0

        for pod in self.pods:
            if self.is_pod_ready(pod):
                ready_count += 1

        total = len(self.pods)

        if ready_count == total:
            status = "PASS"
            message = f"{ready_count}/{total} Pods are Ready."
        elif ready_count > 0:
            status = "WARN"
            message = f"{ready_count}/{total} Pods are Ready."
        else:
            status = "FAIL"
            message = "No matching Pods are Ready."

            self.add_finding(
                "The Service has Pods, but none of them are Ready."
            )

            self.add_recommendation(
                "Check Pod events and container logs: "
                f"kubectl describe pods -n {self.client.namespace} "
                f"-l {selector_string}"
            )

            self.add_recommendation(
                "Then: kubectl logs -n "
                f"{self.client.namespace} -l {selector_string} "
                "--all-containers --tail=100"
            )

        self.add_check(
            "Pod readiness",
            status,
            message,
        )

        self.check_pod_states()

    @staticmethod
    def is_pod_ready(pod: dict[str, Any]) -> bool:

        conditions = pod.get("status", {}).get("conditions", [])

        for condition in conditions:
            if (
                condition.get("type") == "Ready"
                and condition.get("status") == "True"
            ):
                return True

        return False

    # ------------------------------------------------------------------
    # Pod states / probes
    # ------------------------------------------------------------------

    def check_pod_states(self) -> None:

        for pod in self.pods:

            pod_name = pod.get("metadata", {}).get("name", "unknown")

            phase = pod.get("status", {}).get("phase", "Unknown")

            init_statuses = pod.get("status", {}).get(
                "initContainerStatuses",
                [],
            )

            self.check_container_statuses(
                pod_name,
                init_statuses,
                label="Init container",
            )

            if phase != "Running":
                self.add_check(
                    f"Pod state: {pod_name}",
                    "FAIL",
                    f"Pod phase is {phase}.",
                )

                self.add_finding(
                    f"Pod {pod_name} is not Running."
                )

                continue

            statuses = pod.get("status", {}).get(
                "containerStatuses",
                [],
            )

            self.check_container_statuses(
                pod_name,
                statuses,
                label="Container",
            )

    def check_container_statuses(
        self,
        pod_name: str,
        statuses: list[dict[str, Any]],
        label: str,
    ) -> None:

        is_init = label == "Init container"

        for container in statuses:

            container_name = container.get(
                "name",
                "unknown",
            )

            restart_count = container.get(
                "restartCount",
                0,
            )

            state = container.get("state", {})

            waiting = state.get("waiting")

            terminated = state.get("terminated")

            if waiting:
                reason = waiting.get(
                    "reason",
                    "Unknown",
                )

                self.add_check(
                    f"{label}: {pod_name}/{container_name}",
                    "FAIL",
                    f"{label} is waiting: {reason}",
                )

                self.add_finding(
                    f"{pod_name}/{container_name}: {reason}"
                )

            elif terminated:
                reason = terminated.get(
                    "reason",
                    "Unknown",
                )

                exit_code = terminated.get("exitCode")

                if is_init and exit_code == 0:
                    # A successfully-completed init container is
                    # the expected terminal state, not a failure.
                    continue

                self.add_check(
                    f"{label}: {pod_name}/{container_name}",
                    "FAIL",
                    f"{label} terminated: {reason}",
                )

                self.add_finding(
                    f"{pod_name}/{container_name}: terminated ({reason})"
                )

            elif restart_count > 0:

                self.add_check(
                    f"Restarts: {pod_name}/{container_name}",
                    "WARN",
                    f"{label} restarted {restart_count} time(s).",
                )

                self.add_finding(
                    f"{pod_name}/{container_name} has restarted "
                    f"{restart_count} time(s)."
                )

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def check_endpoints(self) -> None:

        endpoints = self.client.run(
            [
                "get",
                "endpoints",
                self.service_name,
            ],
            json_output=True,
            allow_failure=True,
        )

        self.endpoints = endpoints

        if not endpoints:
            self.add_check(
                "Endpoints",
                "FAIL",
                "Could not retrieve Service endpoints.",
            )
            return

        subsets = endpoints.get("subsets", [])

        addresses = []
        not_ready_addresses = []
        not_ready_pod_names = []

        for subset in subsets:

            for address in subset.get("addresses", []):
                addresses.append(
                    address.get("ip", "unknown")
                )

            for address in subset.get("notReadyAddresses", []):
                not_ready_addresses.append(
                    address.get("ip", "unknown")
                )

                target_ref_name = address.get(
                    "targetRef", {}
                ).get("name")

                if target_ref_name:
                    not_ready_pod_names.append(target_ref_name)

        if not addresses:

            self.add_check(
                "Service endpoints",
                "FAIL",
                "Service has no ready endpoints.",
            )

            self.add_finding(
                "The Service has no ready endpoints."
            )

            self.add_recommendation(
                "Inspect endpoint status directly: "
                f"kubectl get endpoints {self.service_name} "
                f"-n {self.client.namespace} -o yaml"
            )

        else:

            self.add_check(
                "Service endpoints",
                "PASS",
                f"Service has {len(addresses)} ready endpoint(s).",
                addresses,
            )

        if not_ready_addresses:

            self.add_check(
                "Not-ready endpoints",
                "WARN",
                f"Service has {len(not_ready_addresses)} "
                f"not-ready endpoint(s).",
                not_ready_addresses,
            )

            self.add_finding(
                "Some Pods behind the Service exist but are "
                "not currently passing readiness checks."
            )

            if not_ready_pod_names:
                pod_list = " ".join(not_ready_pod_names)

                self.add_recommendation(
                    "Check why these Pods are failing readiness: "
                    f"kubectl describe pod -n {self.client.namespace} "
                    f"{pod_list}"
                )

    # ------------------------------------------------------------------
    # Service ports
    # ------------------------------------------------------------------

    def check_service_ports(self) -> None:

        if not self.service:
            return

        service_ports = self.service.get(
            "spec",
            {},
        ).get(
            "ports",
            [],
        )

        if not service_ports:
            self.add_check(
                "Service ports",
                "FAIL",
                "Service has no configured ports.",
            )
            return

        pod_ports_by_number = set()
        pod_ports_by_name = set()

        service_selector = self.service.get("spec", {}).get(
            "selector", {}
        )

        selector_string = ",".join(
            f"{key}={value}"
            for key, value in service_selector.items()
        )

        for pod in self.pods:

            for container in pod.get(
                "spec",
                {},
            ).get(
                "containers",
                [],
            ):

                for port in container.get(
                    "ports",
                    [],
                ):

                    container_port = port.get(
                        "containerPort"
                    )

                    if container_port:
                        pod_ports_by_number.add(container_port)

                    port_name = port.get("name")

                    if port_name:
                        pod_ports_by_name.add(port_name)

        for service_port in service_ports:

            target_port = service_port.get(
                "targetPort"
            )

            if isinstance(target_port, int):

                if not pod_ports_by_number:

                    self.add_check(
                        "Service targetPort",
                        "INFO",
                        f"targetPort {target_port} cannot be "
                        f"verified -- no container ports are "
                        f"declared on the matching Pods.",
                    )

                elif target_port not in pod_ports_by_number:

                    self.add_check(
                        "Service targetPort",
                        "WARN",
                        f"targetPort {target_port} does not "
                        f"match declared container ports.",
                    )

                    self.add_finding(
                        f"Service targetPort {target_port} may not "
                        f"match the application container port."
                    )

                    self.add_recommendation(
                        "Compare the two directly: "
                        f"kubectl get svc {self.service_name} "
                        f"-n {self.client.namespace} "
                        "-o jsonpath='{.spec.ports}' "
                        "&& kubectl get pods -n "
                        f"{self.client.namespace} -l {selector_string} "
                        "-o jsonpath='{.items[0].spec.containers[*].ports}'"
                    )

                else:

                    self.add_check(
                        "Service targetPort",
                        "PASS",
                        f"targetPort {target_port} looks valid.",
                    )

            elif isinstance(target_port, str):

                if not pod_ports_by_name:

                    self.add_check(
                        "Service targetPort",
                        "INFO",
                        f"targetPort '{target_port}' cannot be "
                        f"verified -- no named container ports are "
                        f"declared on the matching Pods.",
                    )

                elif target_port not in pod_ports_by_name:

                    self.add_check(
                        "Service targetPort",
                        "WARN",
                        f"targetPort '{target_port}' does not "
                        f"match any named container port.",
                    )

                    self.add_finding(
                        f"Service targetPort '{target_port}' does "
                        f"not match any container port name -- this "
                        f"will cause the Service to have no valid "
                        f"endpoints."
                    )

                    self.add_recommendation(
                        "Compare the two directly: "
                        f"kubectl get svc {self.service_name} "
                        f"-n {self.client.namespace} "
                        "-o jsonpath='{.spec.ports[*].targetPort}' "
                        "&& kubectl get pods -n "
                        f"{self.client.namespace} -l {selector_string} "
                        "-o jsonpath='{.items[0].spec.containers[*]"
                        ".ports[*].name}'"
                    )

                else:

                    self.add_check(
                        "Service targetPort",
                        "PASS",
                        f"targetPort '{target_port}' looks valid.",
                    )

    # ------------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------------

    def check_probes(self) -> None:

        for pod in self.pods:

            pod_name = pod.get(
                "metadata",
                {},
            ).get(
                "name",
                "unknown",
            )

            containers = pod.get(
                "spec",
                {},
            ).get(
                "containers",
                [],
            )

            for container in containers:

                container_name = container.get(
                    "name",
                    "unknown",
                )

                readiness = container.get(
                    "readinessProbe"
                )

                liveness = container.get(
                    "livenessProbe"
                )

                if not readiness:

                    self.add_check(
                        f"Readiness probe: "
                        f"{pod_name}/{container_name}",
                        "WARN",
                        "No readiness probe configured.",
                    )

                    self.add_recommendation(
                        f"No readinessProbe on '{container_name}' -- "
                        "add one to its Deployment/StatefulSet spec, "
                        "then: kubectl apply -f <manifest>.yaml "
                        f"(or: kubectl edit deployment <name> "
                        f"-n {self.client.namespace})"
                    )

                else:

                    self.add_check(
                        f"Readiness probe: "
                        f"{pod_name}/{container_name}",
                        "PASS",
                        "Readiness probe is configured.",
                    )

                if liveness:

                    self.add_check(
                        f"Liveness probe: "
                        f"{pod_name}/{container_name}",
                        "PASS",
                        "Liveness probe is configured.",
                    )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def check_events(self) -> None:

        events = self.client.run(
            [
                "get",
                "events",
                "--sort-by=.lastTimestamp",
            ],
            allow_failure=True,
        )

        if not events:
            self.add_check(
                "Kubernetes events",
                "WARN",
                "No events could be retrieved.",
            )
            return

        lines = events.splitlines()

        relevant_names = [self.service_name] + [
            pod.get("metadata", {}).get("name", "")
            for pod in self.pods
        ]

        relevant_names = [name for name in relevant_names if name]

        warning_events = [
            line
            for line in lines
            if "Warning" in line
            and any(name in line for name in relevant_names)
        ]

        if warning_events:

            recent = warning_events[-10:]

            self.add_check(
                "Kubernetes events",
                "WARN",
                f"Found {len(warning_events)} warning event(s) "
                f"related to this Service's Pods.",
                recent,
            )

            self.add_finding(
                "Recent Kubernetes warning events were detected "
                "for this Service's Pods."
            )

            self.add_recommendation(
                "Full event list: kubectl get events "
                f"-n {self.client.namespace} --sort-by=.lastTimestamp"
            )

        else:

            self.add_check(
                "Kubernetes events",
                "PASS",
                "No warning events detected for this Service's Pods.",
            )

    # ------------------------------------------------------------------
    # Ingress
    # ------------------------------------------------------------------

    def check_ingress(self) -> None:

        if not self.ingress_name:
            return

        ingress = self.client.run(
            [
                "get",
                "ingress",
                self.ingress_name,
            ],
            json_output=True,
            allow_failure=True,
        )

        self.ingress = ingress

        if not ingress:

            self.add_check(
                "Ingress",
                "FAIL",
                f"Ingress '{self.ingress_name}' was not found.",
            )

            self.add_finding(
                "The specified Ingress does not exist."
            )

            return

        self.add_check(
            "Ingress",
            "PASS",
            f"Ingress '{self.ingress_name}' exists.",
        )

        rules = ingress.get(
            "spec",
            {},
        ).get(
            "rules",
            [],
        )

        backend_services = []

        for rule in rules:

            http = rule.get("http", {})

            for path in http.get("paths", []):

                backend = path.get(
                    "backend",
                    {},
                )

                service = backend.get(
                    "service",
                    {},
                )

                name = service.get("name")

                if name:
                    backend_services.append(name)

        if backend_services and self.service_name not in backend_services:

            self.add_check(
                "Ingress backend",
                "WARN",
                "Ingress does not appear to reference "
                f"Service '{self.service_name}'.",
                backend_services,
            )

            self.add_finding(
                "Ingress routing may point to a different Service."
            )

            self.add_recommendation(
                "Inspect the Ingress rules directly: "
                f"kubectl get ingress {self.ingress_name} "
                f"-n {self.client.namespace} -o yaml"
            )

        elif backend_services:

            self.add_check(
                "Ingress backend",
                "PASS",
                f"Ingress references Service '{self.service_name}'.",
            )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def check_metrics(self) -> None:

        metrics = self.client.run(
            [
                "top",
                "pods",
                "--no-headers",
            ],
            allow_failure=True,
        )

        if not metrics:

            self.add_check(
                "Resource metrics",
                "INFO",
                "Metrics unavailable. metrics-server may not "
                "be installed.",
            )

            return

        relevant = []

        for line in metrics.splitlines():

            if any(
                pod.get("metadata", {}).get("name", "")
                in line
                for pod in self.pods
            ):
                relevant.append(line)

        if relevant:

            self.add_check(
                "Resource metrics",
                "PASS",
                "Pod CPU/memory metrics retrieved.",
                relevant,
            )

    # ------------------------------------------------------------------
    # Component summary (what exists, and its state at a glance)
    # ------------------------------------------------------------------

    def build_component_summary(self) -> None:

        if self.service:

            ports = self.service.get("spec", {}).get("ports", [])

            port_strs = [
                f"{p.get('port')}->{p.get('targetPort')}"
                for p in ports
            ]

            cluster_ip = self.service.get("spec", {}).get(
                "clusterIP", "none"
            )

            self.report.components.append(
                f"{'Service':<11}: {self.service_name}  "
                f"(ClusterIP {cluster_ip}, ports: "
                f"{', '.join(port_strs) or 'none'})"
            )

        else:

            self.report.components.append(
                f"{'Service':<11}: {self.service_name}  (NOT FOUND)"
            )

        if self.pods:

            self.report.components.append(
                f"{f'Pods ({len(self.pods)})':<11}:"
            )

            for pod in self.pods:

                pod_name = pod.get("metadata", {}).get(
                    "name", "unknown"
                )

                phase = pod.get("status", {}).get(
                    "phase", "Unknown"
                )

                ready = (
                    "Ready"
                    if self.is_pod_ready(pod)
                    else "NOT READY"
                )

                self.report.components.append(
                    f"  - {pod_name:<38} {phase:<10} {ready}"
                )

        else:

            self.report.components.append(
                f"{'Pods':<11}: none found"
            )

        if self.endpoints:

            subsets = self.endpoints.get("subsets", [])

            ready_count = sum(
                len(subset.get("addresses", []))
                for subset in subsets
            )

            not_ready_count = sum(
                len(subset.get("notReadyAddresses", []))
                for subset in subsets
            )

            self.report.components.append(
                f"{'Endpoints':<11}: {ready_count} ready, "
                f"{not_ready_count} not-ready"
            )

        if self.ingress_name:

            if self.ingress:

                hosts = [
                    rule.get("host", "*")
                    for rule in self.ingress.get(
                        "spec", {}
                    ).get("rules", [])
                ]

                self.report.components.append(
                    f"{'Ingress':<11}: {self.ingress_name}  "
                    f"(host: {', '.join(hosts) or '*'})"
                )

            else:

                self.report.components.append(
                    f"{'Ingress':<11}: {self.ingress_name}  (NOT FOUND)"
                )

    # ------------------------------------------------------------------
    # Overall diagnosis
    # ------------------------------------------------------------------

    def diagnose(self) -> None:

        failures = [
            check
            for check in self.report.checks
            if check.status == "FAIL"
        ]

        warnings = [
            check
            for check in self.report.checks
            if check.status == "WARN"
        ]

        if failures:

            self.report.findings.insert(
                0,
                f"{len(failures)} critical check(s) failed.",
            )

        elif warnings:

            self.report.findings.insert(
                0,
                f"No critical checks failed, but "
                f"{len(warnings)} warning(s) were detected.",
            )

        else:

            self.report.findings.insert(
                0,
                "No obvious Kubernetes configuration problem "
                "was detected.",
            )

            if self.service:
                selector = self.service.get("spec", {}).get(
                    "selector", {}
                )

                selector_string = ",".join(
                    f"{key}={value}"
                    for key, value in selector.items()
                )

                log_command = (
                    f"kubectl logs -n {self.report.namespace} "
                    f"-l {selector_string} --all-containers --tail=100"
                )
            else:
                log_command = (
                    f"kubectl logs -n {self.report.namespace} <pod-name>"
                )

            self.report.recommendations.append(
                "Kubernetes config looks healthy -- the cause is "
                f"likely inside the application itself. Check logs: "
                f"{log_command}"
            )

    # ------------------------------------------------------------------
    # Run all checks
    # ------------------------------------------------------------------

    def run(self) -> DiagnosticReport:

        if not self.check_service():
            self.build_component_summary()
            self.diagnose()
            return self.report

        self.check_pods()
        self.check_endpoints()
        self.check_service_ports()
        self.check_probes()
        self.check_events()
        self.check_ingress()
        self.check_metrics()

        self.build_component_summary()
        self.diagnose()

        return self.report


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(
    report: DiagnosticReport,
    position: Optional[tuple[int, int]] = None,
) -> None:

    print()
    print("=" * 72)

    if position:
        current, total = position
        print(
            f" Kubernetes 503 Diagnostic Report  "
            f"[{current}/{total}] -- {report.service}"
        )
    else:
        print(" Kubernetes 503 Diagnostic Report")

    print("=" * 72)

    print(f"Timestamp : {report.timestamp}")
    print(f"Context   : {report.context}")
    print(f"Namespace : {report.namespace}")
    print(f"Service   : {report.service}")

    if report.ingress:
        print(f"Ingress   : {report.ingress}")

    print()
    print("-" * 72)
    print("2. COMPONENTS")
    print("-" * 72)

    for line in report.components:
        print(line)

    print()
    print("-" * 72)
    print("3. CHECKS")
    print("-" * 72)
    print()

    for check in report.checks:

        print(f"[{check.status:<4}] {check.name}")
        print(f"       {check.message}")

        for detail in check.details:
            print(f"       - {detail}")

        print("-" * 32)
        print()

    print("-" * 72)
    print("4. FINDINGS")
    print("-" * 72)

    for finding in report.findings:
        print(f"- {finding}")

    print()
    print("-" * 72)
    print("5. RECOMMENDATIONS")
    print("-" * 72)

    for recommendation in report.recommendations:
        print(f"- {recommendation}")

    print()
    print("=" * 72)
    print()


def save_report(
    report: DiagnosticReport,
    output_directory: Path,
) -> Path:

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    filename = (
        f"k8s_503_report_"
        f"{report.namespace}_"
        f"{report.service}_"
        f"{timestamp}.json"
    )

    output_file = output_directory / filename

    output_file.write_text(
        json.dumps(
            asdict(report),
            indent=2,
        ),
        encoding="utf-8",
    )

    return output_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description=(
            "Diagnose common causes of HTTP 503 errors "
            "in Kubernetes applications."
        )
    )

    parser.add_argument(
        "-n",
        "--namespace",
        required=True,
        help="Kubernetes namespace.",
    )

    parser.add_argument(
        "-s",
        "--service",
        required=True,
        help=(
            "Kubernetes Service name. Pass a comma-separated list "
            "(e.g. frontend,tomcat-app,pg-db-postgresql) to diagnose "
            "every tier of a multi-service application in one run."
        ),
    )

    parser.add_argument(
        "-i",
        "--ingress",
        help=(
            "Optional Kubernetes Ingress name. Only checked against "
            "the first Service when multiple are given."
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        default="./reports",
        help="Directory for JSON reports. Default: ./reports",
    )

    return parser.parse_args()


def main() -> int:

    args = parse_arguments()

    client = KubernetesClient(
        namespace=args.namespace
    )

    service_names = [
        name.strip()
        for name in args.service.split(",")
        if name.strip()
    ]

    exit_code = 0
    summary = []

    try:

        for index, service_name in enumerate(service_names):

            # The Ingress fronts one entry-point Service -- only
            # check it against the first Service in the list.
            ingress_name = args.ingress if index == 0 else None

            diagnoser = Kubernetes503Diagnoser(
                client=client,
                service_name=service_name,
                ingress_name=ingress_name,
            )

            report = diagnoser.run()

            position = (
                (index + 1, len(service_names))
                if len(service_names) > 1
                else None
            )

            print_report(report, position=position)

            output_file = save_report(
                report,
                Path(args.output),
            )

            print(f"JSON report saved to: {output_file}")

            failures = [
                check
                for check in report.checks
                if check.status == "FAIL"
            ]

            if failures:
                exit_code = 1
                summary.append(f"[FAIL] {service_name}")
            else:
                summary.append(f"[OK]   {service_name}")

        if len(service_names) > 1:

            print("=" * 72)
            print(" Multi-Service Summary")
            print("=" * 72)

            for line in summary:
                print(line)

            print("=" * 72)
            print()

        return exit_code

    except KubectlError as exc:

        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    except KeyboardInterrupt:

        print(
            "\nInterrupted.",
            file=sys.stderr,
        )

        return 130


if __name__ == "__main__":
    sys.exit(main())