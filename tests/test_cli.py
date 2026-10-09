"""Unit tests for the k8s-toolkit CLI -- Kubernetes503Diagnoser and
save_report are mocked throughout; no real kubectl/cluster access
happens here."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from k8s_toolkit import cli
from k8s_toolkit.kubernetes_client import KubectlError
from k8s_toolkit.models import CheckResult, DiagnosticReport


def make_report(service: str, status: str = "PASS") -> DiagnosticReport:
    return DiagnosticReport(
        timestamp="t",
        context="ctx",
        namespace="ns",
        service=service,
        ingress=None,
        checks=[CheckResult("Service", status, "msg")],
    )


class TestParseArguments:
    def test_requires_namespace_and_service(self):
        with pytest.raises(SystemExit):
            cli.parse_arguments(["diagnose-503"])

    def test_parses_minimum_args(self):
        args = cli.parse_arguments(["diagnose-503", "-n", "ns", "-s", "svc"])

        assert args.namespace == "ns"
        assert args.service == "svc"
        assert args.ingress is None
        assert args.output == "./reports"

    def test_unknown_command_exits(self):
        with pytest.raises(SystemExit):
            cli.parse_arguments(["not-a-real-command"])


class TestRunDiagnose503:
    @patch("k8s_toolkit.cli.save_report")
    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_single_service_healthy_returns_zero(
        self, mock_diagnoser_cls, mock_save, tmp_path
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = make_report("svc")
        mock_diagnoser_cls.return_value = mock_instance
        mock_save.return_value = tmp_path / "report.json"

        args = cli.parse_arguments(["diagnose-503", "-n", "ns", "-s", "svc"])
        exit_code = cli.run_diagnose_503(args)

        assert exit_code == 0
        mock_diagnoser_cls.assert_called_once()

    @patch("k8s_toolkit.cli.save_report")
    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_any_failure_returns_nonzero(
        self, mock_diagnoser_cls, mock_save, tmp_path
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = make_report("svc", status="FAIL")
        mock_diagnoser_cls.return_value = mock_instance
        mock_save.return_value = tmp_path / "report.json"

        args = cli.parse_arguments(["diagnose-503", "-n", "ns", "-s", "svc"])
        exit_code = cli.run_diagnose_503(args)

        assert exit_code == 1

    @patch("k8s_toolkit.cli.save_report")
    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_ingress_only_applied_to_first_service(
        self, mock_diagnoser_cls, mock_save, tmp_path
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = make_report("svc")
        mock_diagnoser_cls.return_value = mock_instance
        mock_save.return_value = tmp_path / "report.json"

        args = cli.parse_arguments(
            [
                "diagnose-503",
                "-n",
                "ns",
                "-s",
                "a,b,c",
                "-i",
                "my-ingress",
            ]
        )
        cli.run_diagnose_503(args)

        calls = mock_diagnoser_cls.call_args_list
        assert calls[0].kwargs["ingress_name"] == "my-ingress"
        assert calls[1].kwargs["ingress_name"] is None
        assert calls[2].kwargs["ingress_name"] is None

    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_kubectl_error_returns_one(self, mock_diagnoser_cls, capsys):
        mock_diagnoser_cls.side_effect = KubectlError("boom")

        args = cli.parse_arguments(["diagnose-503", "-n", "ns", "-s", "svc"])
        exit_code = cli.run_diagnose_503(args)

        assert exit_code == 1
        assert "boom" in capsys.readouterr().err

    @patch("k8s_toolkit.cli.save_report")
    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_multi_service_summary_printed(
        self, mock_diagnoser_cls, mock_save, tmp_path, capsys
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = make_report("svc")
        mock_diagnoser_cls.return_value = mock_instance
        mock_save.return_value = tmp_path / "report.json"

        args = cli.parse_arguments(["diagnose-503", "-n", "ns", "-s", "a,b"])
        cli.run_diagnose_503(args)

        output = capsys.readouterr().out
        assert "Multi-Service Summary" in output


class TestMain:
    @patch("k8s_toolkit.cli.save_report")
    @patch("k8s_toolkit.cli.Kubernetes503Diagnoser")
    def test_main_dispatches_to_diagnose_503(
        self, mock_diagnoser_cls, mock_save, tmp_path
    ):
        mock_instance = MagicMock()
        mock_instance.run.return_value = make_report("svc")
        mock_diagnoser_cls.return_value = mock_instance
        mock_save.return_value = tmp_path / "report.json"

        exit_code = cli.main(["diagnose-503", "-n", "ns", "-s", "svc"])

        assert exit_code == 0
