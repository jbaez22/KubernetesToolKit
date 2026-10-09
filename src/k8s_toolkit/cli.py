#!/usr/bin/env python3
"""k8s-toolkit command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from k8s_toolkit.checks.http_503 import Kubernetes503Diagnoser
from k8s_toolkit.kubernetes_client import KubectlError, KubernetesClient
from k8s_toolkit.reporting.console import print_report
from k8s_toolkit.reporting.json_report import save_report


def _add_diagnose_503_parser(
    subparsers: argparse._SubParsersAction,
) -> None:

    parser = subparsers.add_parser(
        "diagnose-503",
        help=(
            "Diagnose common causes of HTTP 503 errors in a "
            "Kubernetes application."
        ),
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


def parse_arguments(
    argv: list[str] | None = None,
) -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        prog="k8s-toolkit",
        description=(
            "Tools to monitor, diagnose, troubleshoot, and correct "
            "Kubernetes cluster/application issues."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    _add_diagnose_503_parser(subparsers)

    return parser.parse_args(argv)


def run_diagnose_503(args: argparse.Namespace) -> int:

    client = KubernetesClient(namespace=args.namespace)

    service_names = [
        name.strip() for name in args.service.split(",") if name.strip()
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
                check for check in report.checks if check.status == "FAIL"
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


COMMANDS = {
    "diagnose-503": run_diagnose_503,
}


def main(argv: list[str] | None = None) -> int:

    args = parse_arguments(argv)

    handler = COMMANDS[args.command]

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
