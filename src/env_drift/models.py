"""Value objects shared by the scanner, the comparer and the reporters.

These are deliberately plain frozen dataclasses: every stage of the pipeline
(scan -> compare -> report) hands one of these to the next, which keeps the
stages independently testable and free of any I/O knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only needed for the annotation
    from .history import TemplateHistory


@dataclass(frozen=True)
class Usage:
    """A single place in the source tree where an environment variable is read."""

    name: str
    file: str
    line: int
    optional: bool = False
    """True when this read supplies its own fallback, e.g. ``os.getenv("PORT", "8000")``.

    An optional read still deserves documenting - someone cloning the repo wants
    to know the knob exists - but it cannot break a deployment by being unset, so
    it must not fail CI.
    """

    default: str | None = None
    """The fallback value, when it is a literal the scanner can read.

    ``None`` for a required read, and also for an optional read whose fallback is
    computed (``os.getenv("PORT", compute())``) - the flag still says optional,
    but there is no literal to quote in the report.
    """

    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class DriftReport:
    """The outcome of comparing code usage against the env template."""

    missing: tuple[str, ...]
    """Read without a fallback and absent from the template - the failure case."""

    unused: tuple[str, ...]
    """Documented in the template but no longer read anywhere in the scan set."""

    optional_undocumented: tuple[str, ...] = field(default=())
    """Absent from the template, but every read supplies a fallback.

    Worth surfacing so the template can be completed, yet not a build breaker:
    the code runs correctly with the value unset.
    """

    usages: tuple[Usage, ...] = field(default=())
    """Every usage found, so a report can point at file:line for the missing ones."""

    scanned_files: tuple[str, ...] = field(default=())
    template_path: str = ".env.example"
    commit: str = ""
    commit_subject: str = ""
    repo: str = ""

    history: TemplateHistory | None = None
    """How the template itself changed in this push, when a base revision existed.

    Informational: it tells the team what to update in their own `.env`, and never
    affects the exit code.
    """

    @property
    def has_drift(self) -> bool:
        return bool(self.missing or self.unused or self.optional_undocumented)

    @property
    def is_noteworthy(self) -> bool:
        """Whether there is anything at all worth sending to Discord."""
        return self.has_drift or bool(self.history and self.history.has_changes)

    @property
    def fails_build(self) -> bool:
        """Only a required variable absent from the template is worth failing on."""
        return bool(self.missing)

    def locations_for(self, name: str) -> tuple[str, ...]:
        """Where a given variable is read, deduplicated and ordered as found."""
        seen: dict[str, None] = {}
        for usage in self.usages:
            if usage.name == name:
                seen.setdefault(usage.location(), None)
        return tuple(seen)

    def default_for(self, name: str) -> str | None:
        """The fallback shown for an optional variable, if the scanner captured one."""
        for usage in self.usages:
            if usage.name == name and usage.optional:
                return usage.default
        return None
