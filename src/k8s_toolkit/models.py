"""Shared report data models, used by every check module."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    ingress: str | None
    components: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
