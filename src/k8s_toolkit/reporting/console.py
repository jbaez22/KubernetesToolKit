"""Human-readable terminal rendering of a DiagnosticReport."""

from __future__ import annotations

from k8s_toolkit.models import DiagnosticReport


def print_report(
    report: DiagnosticReport,
    position: tuple[int, int] | None = None,
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
