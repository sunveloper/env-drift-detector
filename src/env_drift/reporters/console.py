"""Human-readable terminal output - the local ``--dry-run`` view and the CI log."""

from __future__ import annotations

from ..models import DriftReport
from ..secrets import safe

_MAX_LOCATIONS = 3


def render_console(report: DriftReport, *, detect_unused: bool = True) -> str:
    lines: list[str] = []
    scanned = len(report.scanned_files)
    lines.append(f"env-drift: scanned {scanned} file(s) against {report.template_path}")
    if report.commit:
        subject = report.commit_subject or "(no subject)"
        lines.append(f"  commit {report.commit[:8]}  {subject}")

    if not report.has_drift and not report.committed_secrets:
        lines.append("  OK - no drift found.")
        lines.extend(_history_lines(report))
        return "\n".join(lines)

    if report.committed_secrets:
        lines.append("")
        lines.append(
            f"  COMMITTED CREDENTIAL ({len(report.committed_secrets)}) "
            "- rotate the value, then remove it from the repository:"
        )
        for secret in report.committed_secrets:
            lines.append(f"    ! {secret.name}  {secret.kind} at {secret.where}")

    if report.missing:
        lines.append("")
        lines.append(f"  MISSING from {report.template_path} ({len(report.missing)}):")
        for name in report.missing:
            lines.append(f"    - {name}  read at {_locations(report, name)}")

    if report.optional_undocumented:
        lines.append("")
        lines.append(
            f"  UNDOCUMENTED but has a default ({len(report.optional_undocumented)}) "
            "- does not fail the build:"
        )
        for name in report.optional_undocumented:
            default = safe(report.default_for(name))
            shown = f' (default: "{default}")' if default is not None else ""
            lines.append(f"    - {name}{shown}  read at {_locations(report, name)}")

    if report.unused and detect_unused:
        lines.append("")
        lines.append(f"  UNUSED in code ({len(report.unused)}):")
        for name in report.unused:
            lines.append(f"    - {name}")

    lines.extend(_history_lines(report))
    return "\n".join(lines)


def _history_lines(report: DriftReport) -> list[str]:
    """What changed in the template itself, and what that asks of the team."""
    history = report.history
    if history is None or not history.has_changes:
        return []

    lines = ["", f"  TEMPLATE CHANGED since {history.compared_against}:"]
    for name in history.added:
        lines.append(f"    + {name}  (add it to your .env)")
    for name in history.removed:
        lines.append(f"    - {name}  (no longer used, safe to drop from your .env)")
    for change in history.placeholder_changed:
        lines.append(
            f"    ~ {change.name}  placeholder changed: "
            f'"{safe(change.before)}" -> "{safe(change.after)}"'
        )
    if history.needs_local_action:
        lines.append("    Everyone should refresh their local .env.")
    return lines


def _locations(report: DriftReport, name: str) -> str:
    locations = report.locations_for(name)
    shown = ", ".join(locations[:_MAX_LOCATIONS])
    more = len(locations) - _MAX_LOCATIONS
    if more > 0:
        shown += f" (+{more} more)"
    return shown
