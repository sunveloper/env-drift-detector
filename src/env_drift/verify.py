"""Check whether an environment is actually filled in, without exposing values.

``env-drift check`` asks "is the template complete?". This asks the other half:
"the template is complete - is *my* environment?" It catches the `.env` that was
copied from `.env.example` and never edited, which is the single most common way
a correctly documented variable still ends up wrong.

Security boundary, and the reason this is a separate command:

  * A ``VerifyReport`` holds variable **names** and a verdict. No value, no hash,
    no prefix, no length. ``test_verify.py`` asserts that.
  * Nothing here is persisted and nothing is sent anywhere. This command runs in
    a place that legitimately holds real values - a developer's machine, a deploy
    job - and keeping it output-only means there is no path from a value to an
    external service. That is why ``verify`` has no ``--webhook``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .template import parse_template_entries


class Verdict(str, Enum):
    OK = "ok"
    UNSET = "unset"
    STILL_PLACEHOLDER = "still-placeholder"


# Substrings that mark a template value as obviously a stand-in rather than a
# usable default. Matched case-insensitively.
#
# Deliberately narrow. A template value may be a genuine default - PORT=3000,
# LOG_LEVEL=INFO, ENV_EXAMPLE_PATH=.env.example - and an environment that keeps
# it is correct, not broken. Flagging those would make the command useless in
# exactly the projects that write good templates. Note "example.com" rather than
# "example", so a path like ".env.example" is not caught.
_PLACEHOLDER_MARKERS = (
    "replace",
    "changeme",
    "change-me",
    "change_me",
    "your-",
    "your_",
    "yourname",
    "placeholder",
    "example.com",
    "@example",
    "dummy",
    "fixme",
    "todo",
    "xxx",
    "insert-",
    "insert_",
    "<",
)

# A run of identical filler characters, e.g. 000000000 or aaaaaaaa.
_FILLER_RUN = re.compile(r"(.)\1{5,}")


def looks_like_placeholder(value: str) -> bool:
    """Whether a template value is a stand-in rather than a usable default."""
    if not value:
        # An empty template value declares "no value needed by default", which is
        # a statement about the variable, not a placeholder to be replaced.
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    return bool(_FILLER_RUN.search(value))


@dataclass(frozen=True)
class Finding:
    """One variable that needs attention. Carries no value, by design."""

    name: str
    verdict: Verdict

    def advice(self) -> str:
        if self.verdict is Verdict.UNSET:
            return "not set - copy the entry from the template and fill it in"
        return "still the template placeholder - replace it with a real value"


@dataclass(frozen=True)
class VerifyReport:
    findings: tuple[Finding, ...] = ()
    checked: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    """Names whose template value is empty, so being unset is not a problem."""

    template_path: str = ".env.example"
    source: str = "process environment"

    @property
    def unset(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.findings if f.verdict is Verdict.UNSET)

    @property
    def still_placeholder(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.findings if f.verdict is Verdict.STILL_PLACEHOLDER)

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


def verify_environment(
    template_text: str,
    environment: dict[str, str],
    *,
    strict_placeholder: bool = False,
    template_path: str = ".env.example",
    source: str = "process environment",
) -> VerifyReport:
    """Compare a live environment against the committed template.

    Args:
        template_text: Contents of the env template.
        environment: The live values, e.g. ``dict(os.environ)``. Read, classified
            and discarded - nothing derived from a value is kept.
        strict_placeholder: Flag *any* value still equal to its template value,
            not only ones that look like stand-ins. Useful for a project whose
            template holds no genuine defaults.

    Returns:
        A ``VerifyReport`` containing names and verdicts only.
    """
    entries = parse_template_entries(template_text)

    findings: list[Finding] = []
    optional: list[str] = []

    for name in sorted(entries):
        placeholder = entries[name]
        if not placeholder:
            # The template itself says no value is needed.
            optional.append(name)
            continue

        live = environment.get(name)
        if live is None or not live.strip():
            findings.append(Finding(name=name, verdict=Verdict.UNSET))
            continue

        if live == placeholder and (strict_placeholder or looks_like_placeholder(placeholder)):
            findings.append(Finding(name=name, verdict=Verdict.STILL_PLACEHOLDER))

    return VerifyReport(
        findings=tuple(findings),
        checked=tuple(sorted(entries)),
        optional=tuple(optional),
        template_path=template_path,
        source=source,
    )


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping, for verifying a file directly.

    Uses the same parser as the template, so quoting is handled identically and a
    difference in quotes never reads as a difference in value.
    """
    return parse_template_entries(path.read_text(encoding="utf-8", errors="replace"))


def render_verify_report(report: VerifyReport) -> str:
    """Terminal output. Contains variable names and verdicts, never a value."""
    lines = [
        f"env-drift verify: checked {len(report.checked)} variable(s) from "
        f"{report.template_path} against the {report.source}"
    ]
    if not report.has_findings:
        lines.append("  OK - every documented variable has a real value.")
        if report.optional:
            lines.append(
                f"  {len(report.optional)} variable(s) blank in the template, "
                "so no value was required."
            )
        return "\n".join(lines)

    if report.unset:
        lines.append("")
        lines.append(f"  NOT SET ({len(report.unset)}):")
        for name in report.unset:
            lines.append(f"    - {name}")

    if report.still_placeholder:
        lines.append("")
        lines.append(f"  STILL THE TEMPLATE PLACEHOLDER ({len(report.still_placeholder)}):")
        for name in report.still_placeholder:
            lines.append(f"    - {name}")

    return "\n".join(lines)
