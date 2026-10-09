"""Thin, testable wrapper around the kubectl CLI."""

from __future__ import annotations

import json
import subprocess
from typing import Any


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
