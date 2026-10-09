"""Unit tests for the reporting modules (console + json_report)."""

from __future__ import annotations

import json

from k8s_toolkit.models import CheckResult, DiagnosticReport
from k8s_toolkit.reporting.console import print_report
from k8s_toolkit.reporting.json_report import save_report


def make_report() -> DiagnosticReport:
    return DiagnosticReport(
        timestamp="2026-01-01T00:00:00Z",
        context="docker-desktop",
        namespace="demo-app",
        service="demo-app",
        ingress="demo-app",
        components=["Service    : demo-app"],
        checks=[CheckResult("Service", "PASS", "exists", ["detail"])],
        findings=["No obvious problem was detected."],
        recommendations=["Check logs."],
    )


class TestPrintReport:
    def test_renders_without_error(self, capsys):
        print_report(make_report())

        output = capsys.readouterr().out

        assert "Kubernetes 503 Diagnostic Report" in output
        assert "demo-app" in output
        assert "2. COMPONENTS" in output
        assert "[PASS] Service" in output

    def test_position_label_shown_for_multi_service(self, capsys):
        print_report(make_report(), position=(2, 3))

        output = capsys.readouterr().out

        assert "[2/3] -- demo-app" in output

    def test_no_position_label_for_single_service(self, capsys):
        print_report(make_report(), position=None)

        output = capsys.readouterr().out

        assert "[1/1]" not in output
        assert "--" not in output.splitlines()[2]


class TestSaveReport:
    def test_writes_json_file_with_report_contents(self, tmp_path):
        output_file = save_report(make_report(), tmp_path)

        assert output_file.exists()
        assert output_file.parent == tmp_path

        data = json.loads(output_file.read_text())
        assert data["namespace"] == "demo-app"
        assert data["service"] == "demo-app"
        assert data["checks"][0]["status"] == "PASS"

    def test_creates_output_directory_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b"

        output_file = save_report(make_report(), nested)

        assert output_file.exists()
