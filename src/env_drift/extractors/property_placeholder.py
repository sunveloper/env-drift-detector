"""``${VAR}`` placeholder extractor - Spring property files, and anything sharing
the syntax.

Java code rarely reads an environment variable directly. It reads a Spring
property, and the property file is what resolves to the environment:

.. code-block:: yaml

    # application.yml
    spring:
      datasource:
        url: ${DB_URL}            # the environment variable is here

.. code-block:: java

    @Value("${spring.datasource.url}")   // the Java code only sees a property key

So scanning ``.java`` alone would find almost nothing - the names live in
``application.yml`` and ``application.properties``. This extractor reads them, and
also handles ``@Value("${DB_URL}")`` where a Java annotation names an environment
variable directly, which is why it claims ``.java`` and ``.kt`` too.

Distinguishing an environment variable from a Spring property key: the name must
be upper snake case. Spring's own keys are lower case and dotted
(``spring.datasource.url``) and resolve against a property source, not the
environment. That is the same rule the NestJS extractor uses, for the same reason.

The syntax is shared with docker-compose and shell parameter expansion, so those
files are covered as a side effect. GitHub Actions' ``${{ ... }}`` does not match:
a ``{`` cannot start an upper-snake-case name.
"""

from __future__ import annotations

import re

from ..models import Usage
from .javascript import line_of

SUFFIXES = frozenset({".yml", ".yaml", ".properties", ".java", ".kt"})

_PATTERN = re.compile(
    r"""\$\{
        (?P<name>[A-Z][A-Z0-9_]*)
        (?:
            (?P<sep>:\-|:\?|:|\-|\?)
            (?P<default>[^{}]*)
        )?
        \}""",
    re.VERBOSE,
)

# ``${VAR:?message}`` and ``${VAR?message}`` mean "fail if unset" - the message is
# an error string, not a fallback, so the read stays required.
_REQUIRING_SEPARATORS = frozenset({":?", "?"})


def _strip_comment(line: str) -> str:
    """Remove a trailing comment.

    YAML needs whitespace before ``#`` for it to start a comment, and a ``#`` can
    appear inside a value, so only ``" #"`` counts. ``.properties`` files also use
    a leading ``!``.
    """
    stripped = line.lstrip()
    if stripped.startswith("#") or stripped.startswith("!"):
        return ""
    index = line.find(" #")
    return line[:index] if index != -1 else line


class PropertyPlaceholderExtractor:
    name = "property-placeholder"
    suffixes = SUFFIXES
    filenames = frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        usages: list[Usage] = []
        offset = 0
        for raw_line in source.splitlines(keepends=True):
            line = _strip_comment(raw_line)
            for match in _PATTERN.finditer(line):
                separator = match.group("sep")
                if separator is None or separator in _REQUIRING_SEPARATORS:
                    optional, default = False, None
                else:
                    optional, default = True, match.group("default")
                usages.append(
                    Usage(
                        name=match.group("name"),
                        file=relative_path,
                        line=line_of(source, offset),
                        optional=optional,
                        default=default,
                    )
                )
            offset += len(raw_line)
        return usages
