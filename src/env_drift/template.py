"""Parse a ``.env``-style template into the set of names it documents.

Only the keys matter here - values in a template are placeholders by design, so
they are parsed but discarded. Written by hand rather than delegated to
``python-dotenv`` because the template may legally contain placeholder values
that a strict parser rejects, and a parse failure would silently mask drift.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_PATTERN = re.compile(r"^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_template(path: Path) -> set[str]:
    """Return the variable names declared in an env template file.

    Raises:
        FileNotFoundError: if the template is missing. That is a real
            configuration error - failing loudly beats reporting every variable
            in the codebase as "missing".
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_template_text(text)


def parse_template_text(text: str) -> set[str]:
    names: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if match:
            names.add(match.group("name"))
    return names
