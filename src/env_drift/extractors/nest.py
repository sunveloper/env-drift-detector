"""NestJS extractor: reads through ``ConfigService``.

A Nest project rarely touches ``process.env`` outside its config module. The rest
of the codebase injects ``ConfigService`` and calls ``get``, so without this
extractor almost every variable in a Nest service is invisible:

    this.configService.get<string>('DATABASE_URL')
    configService.get('PORT', 3000)
    this.config.getOrThrow('JWT_SECRET')

Two deliberate restrictions keep the false-positive rate down, because
``ConfigService`` also serves non-environment configuration:

  * The receiver name must contain "config" - ``configService``, ``config``,
    ``appConfig``. A bare ``service.get('X')`` is not a config read.
  * The key must look like an environment variable: upper snake case. Nest's
    namespaced config keys are lower or dotted (``app.port``, ``database.host``)
    and resolve against a config object, not the environment, so they are skipped.
"""

from __future__ import annotations

import re

from ..models import Usage
from .javascript import FALLBACK_PATTERN, SUFFIXES, fallback_from_match, line_of

# Upper snake case only - see the module docstring for why.
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

_PATTERN = re.compile(
    r"""(?:this\s*\.\s*)?                       # optional this.
        (?P<receiver>[A-Za-z_$][A-Za-z0-9_$]*)  # configService / config / appConfig
        \s*\.\s*
        (?P<method>get|getOrThrow)
        \s*(?:<[^<>()]*>)?\s*                   # optional TS generic: get<string>
        \(\s*
        (?P<quote>['"`])(?P<key>[^'"`]+)(?P=quote)
        \s*
        (?P<second>,\s*(?:
              (?P<squote>['"`])(?P<sliteral>[^'"`]*)(?P=squote)
            | (?P<snumber>-?\d+(?:\.\d+)?)
            | (?P<sboolean>true|false)
            | (?P<sother>[^),]+)
        ))?
        \s*\)"""
    + FALLBACK_PATTERN,
    re.VERBOSE,
)


def _is_config_receiver(receiver: str) -> bool:
    return "config" in receiver.lower()


def _second_argument_fallback(match: re.Match[str]) -> tuple[bool, str | None]:
    """ConfigService.get(key, default) - the second argument is the fallback."""
    if match.group("second") is None:
        return False, None
    literal = match.group("sliteral")
    if literal is not None:
        return True, literal
    return True, match.group("snumber") or match.group("sboolean")


class NestConfigExtractor:
    name = "nest-config"
    suffixes = SUFFIXES
    filenames = frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        usages: list[Usage] = []
        for match in _PATTERN.finditer(source):
            if not _is_config_receiver(match.group("receiver")):
                continue
            key = match.group("key").strip()
            if not _ENV_NAME.match(key):
                continue

            # getOrThrow states outright that an unset value is fatal, so it stays
            # required even if something downstream supplies a fallback.
            if match.group("method") == "getOrThrow":
                optional, default = False, None
            else:
                optional, default = _second_argument_fallback(match)
                if not optional:
                    optional, default = fallback_from_match(match)

            usages.append(
                Usage(
                    name=key,
                    file=relative_path,
                    line=line_of(source, match.start()),
                    optional=optional,
                    default=default,
                )
            )
        return usages
