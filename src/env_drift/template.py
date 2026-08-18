"""Parse a ``.env``-style template into the names - and placeholders - it declares.

Written by hand rather than delegated to ``python-dotenv`` because the template
may legally contain placeholder values that a strict parser rejects, and a parse
failure would silently mask drift.

Placeholder values are parsed as well as names, so a change to one can be
reported. They are safe to handle: a template holds placeholders by definition,
and it is committed to the repository. Real values are never read anywhere in
this tool - see ``history.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$"
)


def parse_template(path: Path) -> set[str]:
    """Return the variable names declared in an env template file.

    Raises:
        FileNotFoundError: if the template is missing. That is a real
            configuration error - failing loudly beats reporting every variable
            in the codebase as "missing".
    """
    return parse_template_text(path.read_text(encoding="utf-8", errors="replace"))


def parse_template_text(text: str) -> set[str]:
    return set(parse_template_entries(text))


def parse_template_entries(text: str) -> dict[str, str]:
    """Return ``{name: placeholder}`` for every declaration in the template.

    A later declaration of the same name wins, matching how ``.env`` loaders
    behave. Surrounding quotes are stripped so ``A="x"`` and ``A=x`` compare
    equal - a change in quoting style is not a change in configuration.
    """
    entries: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if match:
            entries[match.group("name")] = _clean_value(match.group("value"))
    return entries


def _clean_value(raw: str) -> str:
    value = raw.strip()
    # Strip a trailing inline comment, but only when it is separated by
    # whitespace: a '#' inside a URL fragment or a password placeholder is part
    # of the value.
    hash_index = value.find(" #")
    if hash_index != -1:
        value = value[:hash_index].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value
