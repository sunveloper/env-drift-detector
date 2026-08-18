"""JS/TS extractor: ``process.env`` and ``import.meta.env`` access.

No stdlib JS parser exists, so this is a targeted regex. It over-reports rather
than under-reports: ``process.env.X`` inside a comment counts as a usage, which
is the safer direction for a tool whose job is to stop an unset variable
reaching production.

Shared helpers live here because the NestJS extractor needs the same
fallback-literal handling.
"""

from __future__ import annotations

import re

from ..models import Usage

SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})

# A ?? or || fallback immediately after the read. The literal is captured when
# there is one; a computed fallback still marks the read optional.
FALLBACK_PATTERN = r"""
    (?P<fallback>
        \s*(?:\?\?|\|\|)\s*
        (?:
            (?P<fquote>['"`])(?P<fliteral>[^'"`]*)(?P=fquote)
          | (?P<fnumber>-?\d+(?:\.\d+)?)
          | (?P<fboolean>true|false)
        )?
    )?
"""

_PATTERN = re.compile(
    r"""(?:process|import\.meta)\.env
        (?:
            \s*\.\s*(?P<dotted>[A-Za-z_][A-Za-z0-9_]*)
          | \s*\[\s*(?P<quote>['"`])(?P<bracket>[^'"`]+)(?P=quote)\s*\]
        )"""
    + FALLBACK_PATTERN,
    re.VERBOSE,
)


def fallback_from_match(match: re.Match[str]) -> tuple[bool, str | None]:
    """Read the shared fallback groups out of a match.

    Returns ``(optional, default)``. ``default`` is None when the fallback is
    computed rather than literal - optional is still True, there is simply nothing
    to quote in the report.
    """
    if match.group("fallback") is None:
        return False, None
    literal = match.group("fliteral")
    if literal is not None:
        return True, literal
    return True, match.group("fnumber") or match.group("fboolean")


def line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


class JavaScriptExtractor:
    name = "javascript"
    suffixes = SUFFIXES
    filenames = frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        usages: list[Usage] = []
        for match in _PATTERN.finditer(source):
            name = (match.group("dotted") or match.group("bracket") or "").strip()
            if not name:
                continue
            optional, default = fallback_from_match(match)
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
