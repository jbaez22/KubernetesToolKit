"""Unit tests for KubernetesClient -- all subprocess calls are mocked."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from k8s_toolkit.kubernetes_client import KubectlError, KubernetesClient


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class TestKubernetesClientRun:
    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_builds_expected_command(self, mock_run):
        mock_run.return_value = _completed(stdout="ok")

        client = KubernetesClient(namespace="demo-app")
        client.run(["get", "pods"])

        called_command = mock_run.call_args[0][0]
        assert called_command == ["kubectl", "get", "pods", "-n", "demo-app"]

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_json_output_appends_o_json_flag(self, mock_run):
        mock_run.return_value = _completed(stdout='{"kind": "Pod"}')

        client = KubernetesClient(namespace="demo-app")
        client.run(["get", "pods"], json_output=True)

        called_command = mock_run.call_args[0][0]
        assert called_command[-2:] == ["-o", "json"]

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_json_output_parses_valid_json(self, mock_run):
        mock_run.return_value = _completed(stdout='{"kind": "Pod"}')

        client = KubernetesClient(namespace="demo-app")
        result = client.run(["get", "pod", "x"], json_output=True)

        assert result == {"kind": "Pod"}

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_json_output_invalid_json_raises(self, mock_run):
        mock_run.return_value = _completed(stdout="not json")

        client = KubernetesClient(namespace="demo-app")

        with pytest.raises(KubectlError, match="invalid JSON"):
            client.run(["get", "pod", "x"], json_output=True)

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_plain_output_is_stripped(self, mock_run):
        mock_run.return_value = _completed(stdout="  hello  \n")

        client = KubernetesClient(namespace="demo-app")
        result = client.run(["get", "events"])

        assert result == "hello"

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_failure_with_allow_failure_returns_none(self, mock_run):
        mock_run.return_value = _completed(stderr="not found", returncode=1)

        client = KubernetesClient(namespace="demo-app")
        result = client.run(["get", "pod", "x"], allow_failure=True)

        assert result is None

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_failure_without_allow_failure_raises(self, mock_run):
        mock_run.return_value = _completed(stderr="not found", returncode=1)

        client = KubernetesClient(namespace="demo-app")

        with pytest.raises(KubectlError, match="not found"):
            client.run(["get", "pod", "x"], allow_failure=False)

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_kubectl_not_found_raises_kubectl_error(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        client = KubernetesClient(namespace="demo-app")

        with pytest.raises(KubectlError, match="was not found"):
            client.run(["get", "pods"])

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_timeout_raises_kubectl_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="kubectl", timeout=30
        )

        client = KubernetesClient(namespace="demo-app")

        with pytest.raises(KubectlError, match="timed out"):
            client.run(["get", "pods"])


class TestGetContext:
    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_returns_current_context_on_success(self, mock_run):
        mock_run.return_value = _completed(stdout="docker-desktop\n")

        client = KubernetesClient(namespace="demo-app")

        assert client.get_context() == "docker-desktop"

    @patch("k8s_toolkit.kubernetes_client.subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run):
        mock_run.return_value = _completed(returncode=1)

        client = KubernetesClient(namespace="demo-app")

        assert client.get_context() == "unknown"
