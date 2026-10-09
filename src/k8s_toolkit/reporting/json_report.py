"""Persist a DiagnosticReport to a timestamped JSON file."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from k8s_toolkit.models import DiagnosticReport


def save_report(
    report: DiagnosticReport,
    output_directory: Path,
) -> Path:

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = (
        f"k8s_503_report_{report.namespace}_{report.service}_{timestamp}.json"
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
