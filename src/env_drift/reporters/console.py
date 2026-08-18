"""Human-readable terminal output - the local ``--dry-run`` view and the CI log."""

from __future__ import annotations

from ..models import DriftReport

_MAX_LOCATIONS = 3


def render_console(report: DriftReport, *, detect_unused: bool = True) -> str:
    lines: list[str] = []
    scanned = len(report.scanned_files)
    lines.append(f"env-drift: scanned {scanned} file(s) against {report.template_path}")
    if report.commit:
        subject = report.commit_subject or "(no subject)"
        lines.append(f"  commit {report.commit[:8]}  {subject}")

    if not report.has_drift:
        lines.append("  OK - no drift found.")
        return "\n".join(lines)

    if report.missing:
        lines.append("")
        lines.append(f"  MISSING from {report.template_path} ({len(report.missing)}):")
        for name in report.missing:
            locations = report.locations_for(name)
            shown = ", ".join(locations[:_MAX_LOCATIONS])
            more = len(locations) - _MAX_LOCATIONS
            if more > 0:
                shown += f" (+{more} more)"
            lines.append(f"    - {name}  read at {shown}")

    if report.unused and detect_unused:
        lines.append("")
        lines.append(f"  UNUSED in code ({len(report.unused)}):")
        for name in report.unused:
            lines.append(f"    - {name}")

    return "\n".join(lines)
