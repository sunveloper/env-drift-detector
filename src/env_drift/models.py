"""Value objects shared by the scanner, the comparer and the reporters.

These are deliberately plain frozen dataclasses: every stage of the pipeline
(scan -> compare -> report) hands one of these to the next, which keeps the
stages independently testable and free of any I/O knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Usage:
    """A single place in the source tree where an environment variable is read."""

    name: str
    file: str
    line: int

    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class DriftReport:
    """The outcome of comparing code usage against the env template."""

    missing: tuple[str, ...]
    """Read by the code but absent from the template - the failure case."""

    unused: tuple[str, ...]
    """Documented in the template but no longer read anywhere in the scan set."""

    usages: tuple[Usage, ...] = field(default=())
    """Every usage found, so a report can point at file:line for the missing ones."""

    scanned_files: tuple[str, ...] = field(default=())
    template_path: str = ".env.example"
    commit: str = ""
    commit_subject: str = ""
    repo: str = ""

    @property
    def has_drift(self) -> bool:
        return bool(self.missing or self.unused)

    def locations_for(self, name: str) -> tuple[str, ...]:
        """Where a given variable is read, deduplicated and ordered as found."""
        seen: dict[str, None] = {}
        for usage in self.usages:
            if usage.name == name:
                seen.setdefault(usage.location(), None)
        return tuple(seen)
