"""Java and Kotlin extractor: reads that bypass the Spring property layer.

``System.getenv("DB_URL")`` and ``System.getProperty("db.url")`` go straight to the
runtime rather than through ``application.yml``, so the property-placeholder
extractor cannot see them.

``System.getProperty`` reads a JVM system property, not an environment variable.
It is included because in practice the value arrives as ``-Dkey=$KEY`` from a start
script or container entrypoint, which makes it part of the same configuration
surface a `.env` documents. Its keys are dotted and lower case by convention, so
only upper-snake-case ones are treated as environment variables - the same rule
applied everywhere else in this tool.
"""

from __future__ import annotations

import re

from ..models import Usage
from .javascript import line_of

SUFFIXES = frozenset({".java", ".kt"})

# Upper snake case only. A dotted lower-case key is a JVM property namespace, not
# an environment variable name.
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

_PATTERN = re.compile(
    r"""System\s*\.\s*(?P<method>getenv|getProperty)\s*\(\s*
        (?P<quote>")(?P<name>[^"]+)(?P=quote)
        (?:
            \s*,\s*
            (?:
                "(?P<sliteral>[^"]*)"
              | (?P<snumber>-?\d+(?:\.\d+)?)
              | (?P<sboolean>true|false)
              | (?P<sother>[^),]+)
            )
        )?
        \s*\)
        (?P<fallback>
            \s*(?:\?:|\|\|)\s*        # Kotlin elvis, or a Java-side || guard
            (?:"(?P<fliteral>[^"]*)")?
        )?""",
    re.VERBOSE,
)


def _fallback(match: re.Match[str]) -> tuple[bool, str | None]:
    """Whether the read has a fallback, and its literal if one is readable."""
    literal = match.group("sliteral")
    if literal is not None:
        return True, literal
    number_or_bool = match.group("snumber") or match.group("sboolean")
    if number_or_bool is not None:
        return True, number_or_bool
    if match.group("sother") is not None:
        # A computed second argument is still a default, just not a quotable one.
        return True, None
    if match.group("fallback") is not None:
        return True, match.group("fliteral")
    return False, None


class JavaExtractor:
    name = "java"
    suffixes = SUFFIXES
    filenames = frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        usages: list[Usage] = []
        for match in _PATTERN.finditer(source):
            name = match.group("name").strip()
            if not _ENV_NAME.match(name):
                continue
            optional, default = _fallback(match)
            usages.append(
                Usage(
                    name=name,
                    file=relative_path,
                    line=line_of(source, match.start()),
                    optional=optional,
                    default=default,
                )
            )
        return usages
