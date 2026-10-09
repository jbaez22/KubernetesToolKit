"""Unit tests for Kubernetes503Diagnoser -- the KubernetesClient is a
mock throughout; no real kubectl/cluster access happens here."""

from __future__ import annotations

from unittest.mock import MagicMock

from k8s_toolkit.checks.http_503 import Kubernetes503Diagnoser


def make_client(namespace: str = "demo-app") -> MagicMock:
    client = MagicMock()
    client.namespace = namespace
    client.get_context.return_value = "docker-desktop"
    return client


def make_diagnoser(client=None, service_name="demo-app", ingress_name=None):
    return Kubernetes503Diagnoser(
        client=client or make_client(),
        service_name=service_name,
        ingress_name=ingress_name,
    )


def make_pod(
    name: str,
    ready: bool = True,
    phase: str = "Running",
    containers: list[dict] | None = None,
    restart_count: int = 0,
    container_ports: list[dict] | None = None,
):
    return {
        "metadata": {"name": name},
        "status": {
            "phase": phase,
            "conditions": [
                {"type": "Ready", "status": "True" if ready else "False"}
            ],
            "containerStatuses": containers
            if containers is not None
            else [
                {
                    "name": "web",
                    "restartCount": restart_count,
                    "state": {}
                    if ready
                    else {"waiting": {"reason": "CrashLoopBackOff"}},
                }
            ],
        },
        "spec": {
            "containers": [
                {
                    "name": "web",
                    "ports": container_ports
                    if container_ports is not None
                    else [{"name": "http", "containerPort": 80}],
                    "readinessProbe": {
                        "httpGet": {"path": "/", "port": "http"}
                    },
                    "livenessProbe": {
                        "httpGet": {"path": "/", "port": "http"}
                    },
                }
            ]
        },
    }


class TestCheckService:
    def test_service_not_found_fails(self):
        client = make_client()
        client.run.return_value = None

        diagnoser = make_diagnoser(client=client)
        found = diagnoser.check_service()

        assert found is False
        assert diagnoser.report.checks[-1].status == "FAIL"
        assert "does not exist" in diagnoser.report.findings[0]
        assert any(
            "kubectl get svc" in rec
            for rec in diagnoser.report.recommendations
        )

    def test_service_found_passes(self):
        client = make_client()
        client.run.return_value = {
            "spec": {
                "selector": {"app": "demo-app"},
                "ports": [{"port": 80, "targetPort": "http"}],
            }
        }

        diagnoser = make_diagnoser(client=client)
        found = diagnoser.check_service()

        assert found is True
        assert diagnoser.report.checks[-1].status == "PASS"

    def test_service_without_selector_warns(self):
        client = make_client()
        client.run.return_value = {"spec": {"selector": {}, "ports": []}}

        diagnoser = make_diagnoser(client=client)
        diagnoser.check_service()

        statuses = [c.status for c in diagnoser.report.checks]
        assert "WARN" in statuses


class TestCheckPods:
    def test_no_pods_match_selector_fails(self):
        client = make_client()
        client.run.return_value = None

        diagnoser = make_diagnoser(client=client)
        diagnoser.service = {"spec": {"selector": {"app": "demo-app"}}}
        diagnoser.check_pods()

        assert diagnoser.report.checks[-1].status == "FAIL"
        assert any(
            "--show-labels" in rec for rec in diagnoser.report.recommendations
        )

    def test_all_pods_ready_passes(self):
        client = make_client()
        client.run.return_value = {
            "items": [make_pod("pod-a"), make_pod("pod-b")]
        }

        diagnoser = make_diagnoser(client=client)
        diagnoser.service = {"spec": {"selector": {"app": "demo-app"}}}
        diagnoser.check_pods()

        readiness_check = next(
            c for c in diagnoser.report.checks if c.name == "Pod readiness"
        )
        assert readiness_check.status == "PASS"
        assert "2/2" in readiness_check.message

    def test_no_pods_ready_fails_with_log_recommendation(self):
        client = make_client()
        client.run.return_value = {"items": [make_pod("pod-a", ready=False)]}

        diagnoser = make_diagnoser(client=client)
        diagnoser.service = {"spec": {"selector": {"app": "demo-app"}}}
        diagnoser.check_pods()

        readiness_check = next(
            c for c in diagnoser.report.checks if c.name == "Pod readiness"
        )
        assert readiness_check.status == "FAIL"
        assert any(
            "kubectl logs" in rec for rec in diagnoser.report.recommendations
        )


class TestCheckContainerStatuses:
    def test_init_container_success_is_not_a_failure(self):
        diagnoser = make_diagnoser()

        diagnoser.check_container_statuses(
            "pod-a",
            [
                {
                    "name": "wait-for-db",
                    "restartCount": 0,
                    "state": {
                        "terminated": {"reason": "Completed", "exitCode": 0}
                    },
                }
            ],
            label="Init container",
        )

        assert diagnoser.report.checks == []

    def test_init_container_waiting_is_a_failure(self):
        diagnoser = make_diagnoser()

        diagnoser.check_container_statuses(
            "pod-a",
            [
                {
                    "name": "wait-for-db",
                    "restartCount": 0,
                    "state": {"waiting": {"reason": "PodInitializing"}},
                }
            ],
            label="Init container",
        )

        assert diagnoser.report.checks[-1].status == "FAIL"

    def test_container_restart_is_a_warning(self):
        diagnoser = make_diagnoser()

        diagnoser.check_container_statuses(
            "pod-a",
            [{"name": "web", "restartCount": 3, "state": {}}],
            label="Container",
        )

        assert diagnoser.report.checks[-1].status == "WARN"
        assert "3 time(s)" in diagnoser.report.checks[-1].message


class TestCheckEndpoints:
    def test_no_ready_endpoints_fails(self):
        client = make_client()
        client.run.return_value = {"subsets": []}

        diagnoser = make_diagnoser(client=client)
        diagnoser.check_endpoints()

        assert diagnoser.report.checks[-1].status == "FAIL"

    def test_not_ready_addresses_warn_with_pod_names(self):
        client = make_client()
        client.run.return_value = {
            "subsets": [
                {
                    "addresses": [{"ip": "10.0.0.1"}],
                    "notReadyAddresses": [
                        {
                            "ip": "10.0.0.2",
                            "targetRef": {"name": "pod-b"},
                        }
                    ],
                }
            ]
        }

        diagnoser = make_diagnoser(client=client)
        diagnoser.check_endpoints()

        not_ready_check = next(
            c
            for c in diagnoser.report.checks
            if c.name == "Not-ready endpoints"
        )
        assert not_ready_check.status == "WARN"
        assert any("pod-b" in rec for rec in diagnoser.report.recommendations)


class TestCheckServicePorts:
    def test_numeric_target_port_mismatch_warns(self):
        diagnoser = make_diagnoser()
        diagnoser.service = {
            "spec": {
                "selector": {"app": "demo-app"},
                "ports": [{"port": 80, "targetPort": 9999}],
            }
        }
        diagnoser.pods = [
            make_pod("pod-a", container_ports=[{"containerPort": 8080}])
        ]

        diagnoser.check_service_ports()

        assert diagnoser.report.checks[-1].status == "WARN"

    def test_named_target_port_cannot_verify_is_info_not_pass(self):
        diagnoser = make_diagnoser()
        diagnoser.service = {
            "spec": {
                "selector": {"app": "demo-app"},
                "ports": [{"port": 80, "targetPort": "http"}],
            }
        }
        diagnoser.pods = [make_pod("pod-a", container_ports=[])]

        diagnoser.check_service_ports()

        assert diagnoser.report.checks[-1].status == "INFO"

    def test_matching_named_target_port_passes(self):
        diagnoser = make_diagnoser()
        diagnoser.service = {
            "spec": {
                "selector": {"app": "demo-app"},
                "ports": [{"port": 80, "targetPort": "http"}],
            }
        }
        diagnoser.pods = [make_pod("pod-a")]

        diagnoser.check_service_ports()

        assert diagnoser.report.checks[-1].status == "PASS"


class TestIsPodReady:
    def test_ready_pod(self):
        assert Kubernetes503Diagnoser.is_pod_ready(make_pod("x", ready=True))

    def test_not_ready_pod(self):
        assert not Kubernetes503Diagnoser.is_pod_ready(
            make_pod("x", ready=False)
        )


class TestRunHappyPath:
    def test_fully_healthy_service_has_no_failures(self):
        client = make_client()

        def side_effect(args, json_output=False, allow_failure=False):
            verb, resource = args[0], args[1]

            if verb == "top":
                return None
            if resource == "service":
                return {
                    "spec": {
                        "selector": {"app": "demo-app"},
                        "ports": [{"port": 80, "targetPort": "http"}],
                    }
                }
            if resource == "pods":
                return {"items": [make_pod("pod-a")]}
            if resource == "endpoints":
                return {"subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]}
            if resource == "events":
                return "no events"

            return None

        client.run.side_effect = side_effect

        diagnoser = make_diagnoser(client=client)
        report = diagnoser.run()

        failures = [c for c in report.checks if c.status == "FAIL"]
        assert failures == []


class TestCheckProbes:
    def test_missing_readiness_probe_warns_with_recommendation(self):
        diagnoser = make_diagnoser()
        diagnoser.pods = [
            make_pod(
                "pod-a",
                containers=[{"name": "web", "restartCount": 0, "state": {}}],
            )
        ]
        diagnoser.pods[0]["spec"]["containers"][0].pop("readinessProbe")

        diagnoser.check_probes()

        readiness_check = next(
            c for c in diagnoser.report.checks if "Readiness probe" in c.name
        )
        assert readiness_check.status == "WARN"
        assert any(
            "readinessProbe" in rec for rec in diagnoser.report.recommendations
        )

    def test_configured_probes_pass(self):
        diagnoser = make_diagnoser()
        diagnoser.pods = [make_pod("pod-a")]

        diagnoser.check_probes()

        statuses = {c.name: c.status for c in diagnoser.report.checks}
        assert statuses["Readiness probe: pod-a/web"] == "PASS"
        assert statuses["Liveness probe: pod-a/web"] == "PASS"


class TestCheckEvents:
    def test_no_events_available_warns(self):
        client = make_client()
        client.run.return_value = None

        diagnoser = make_diagnoser(client=client)
        diagnoser.check_events()

        assert diagnoser.report.checks[-1].status == "WARN"

    def test_relevant_warning_event_is_flagged(self):
        client = make_client()
        client.run.return_value = (
            "1m   Warning   Failed   pod/demo-app-xyz   boom"
        )

        diagnoser = make_diagnoser(client=client)
        diagnoser.pods = [make_pod("demo-app-xyz")]
        diagnoser.check_events()

        assert diagnoser.report.checks[-1].status == "WARN"
        assert any(
            "kubectl get events" in rec
            for rec in diagnoser.report.recommendations
        )

    def test_unrelated_warning_event_is_not_flagged(self):
        client = make_client(namespace="demo-app")
        client.run.return_value = (
            "1m   Warning   Failed   pod/other-app-xyz   boom"
        )

        diagnoser = make_diagnoser(client=client, service_name="demo-app")
        diagnoser.pods = [make_pod("demo-app-xyz")]
        diagnoser.check_events()

        assert diagnoser.report.checks[-1].status == "PASS"


class TestCheckIngress:
    def test_no_ingress_name_is_a_noop(self):
        diagnoser = make_diagnoser(ingress_name=None)
        diagnoser.check_ingress()

        assert diagnoser.report.checks == []

    def test_ingress_not_found_fails(self):
        client = make_client()
        client.run.return_value = None

        diagnoser = make_diagnoser(client=client, ingress_name="demo-ing")
        diagnoser.check_ingress()

        assert diagnoser.report.checks[-1].status == "FAIL"

    def test_ingress_backend_mismatch_warns(self):
        client = make_client()
        client.run.return_value = {
            "spec": {
                "rules": [
                    {
                        "http": {
                            "paths": [
                                {"backend": {"service": {"name": "other-svc"}}}
                            ]
                        }
                    }
                ]
            }
        }

        diagnoser = make_diagnoser(
            client=client,
            service_name="demo-app",
            ingress_name="demo-ing",
        )
        diagnoser.check_ingress()

        backend_check = next(
            c for c in diagnoser.report.checks if c.name == "Ingress backend"
        )
        assert backend_check.status == "WARN"

    def test_ingress_backend_match_passes(self):
        client = make_client()
        client.run.return_value = {
            "spec": {
                "rules": [
                    {
                        "http": {
                            "paths": [
                                {"backend": {"service": {"name": "demo-app"}}}
                            ]
                        }
                    }
                ]
            }
        }

        diagnoser = make_diagnoser(
            client=client,
            service_name="demo-app",
            ingress_name="demo-ing",
        )
        diagnoser.check_ingress()

        backend_check = next(
            c for c in diagnoser.report.checks if c.name == "Ingress backend"
        )
        assert backend_check.status == "PASS"


class TestCheckMetrics:
    def test_metrics_unavailable_is_info(self):
        client = make_client()
        client.run.return_value = None

        diagnoser = make_diagnoser(client=client)
        diagnoser.check_metrics()

        assert diagnoser.report.checks[-1].status == "INFO"

    def test_relevant_metrics_pass(self):
        client = make_client()
        client.run.return_value = "pod-a   5m   10Mi"

        diagnoser = make_diagnoser(client=client)
        diagnoser.pods = [make_pod("pod-a")]
        diagnoser.check_metrics()

        assert diagnoser.report.checks[-1].status == "PASS"


class TestBuildComponentSummary:
    def test_service_not_found_and_no_pods(self):
        diagnoser = make_diagnoser()
        diagnoser.build_component_summary()

        assert any("NOT FOUND" in line for line in diagnoser.report.components)
        assert any(
            "none found" in line for line in diagnoser.report.components
        )

    def test_healthy_state_lists_pods_and_endpoints(self):
        diagnoser = make_diagnoser()
        diagnoser.service = {
            "spec": {"ports": [{"port": 80, "targetPort": "http"}]}
        }
        diagnoser.pods = [make_pod("pod-a")]
        diagnoser.endpoints = {
            "subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]
        }

        diagnoser.build_component_summary()

        summary = "\n".join(diagnoser.report.components)
        assert "pod-a" in summary
        assert "1 ready, 0 not-ready" in summary


class TestDiagnose:
    def test_failures_present_summarized_first(self):
        diagnoser = make_diagnoser()
        diagnoser.add_check("Service", "FAIL", "boom")

        diagnoser.diagnose()

        assert "critical check(s) failed" in diagnoser.report.findings[0]

    def test_all_pass_recommends_checking_app_logs(self):
        diagnoser = make_diagnoser()
        diagnoser.service = {"spec": {"selector": {"app": "demo-app"}}}

        diagnoser.diagnose()

        assert "No obvious" in diagnoser.report.findings[0]
        assert any(
            "kubectl logs" in rec for rec in diagnoser.report.recommendations
        )
