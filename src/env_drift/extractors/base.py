"""The extractor contract and the registry that resolves a file to its extractors.

Adding support for a stack means adding a module here and registering it. The
scanner, the comparison and the reporters stay untouched, because every extractor
speaks the same output language: a list of ``Usage``.

A file can be claimed by more than one extractor. A NestJS service reads config
both through ``process.env`` and through ``ConfigService``, and both extractors
run over the same ``.ts`` file rather than one having to know about the other.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Protocol, runtime_checkable

from ..models import Usage

NO_FALLBACK: tuple[bool, str | None] = (False, None)
"""The ``(optional, default)`` pair for a read that supplies no fallback."""


@runtime_checkable
class Extractor(Protocol):
    """Finds environment variable reads in one flavour of source file."""

    name: str
    """Short identifier, used in test failures and debugging output."""

    suffixes: frozenset[str]
    """Lowercase file suffixes this extractor claims, e.g. ``{".py"}``."""

    filenames: frozenset[str]
    """Exact lowercase file names claimed regardless of suffix.

    Needed for stacks whose configuration lives in a specifically named file -
    ``application.yml`` for Spring - where the suffix alone says nothing.
    """

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        """Return every env var read found in ``source``.

        Must not raise on malformed input. The tool runs in CI against whatever
        was pushed, and one unparseable file should not hide the drift in every
        other file - return an empty list instead.
        """
        ...


class Registry:
    """Holds the registered extractors and answers "who handles this file?"."""

    def __init__(self, extractors: list[Extractor] | None = None) -> None:
        self._extractors: list[Extractor] = list(extractors or [])

    def register(self, extractor: Extractor) -> Extractor:
        """Add an extractor. Returns it, so this can be used as a decorator."""
        self._extractors.append(extractor)
        return extractor

    def all(self) -> tuple[Extractor, ...]:
        return tuple(self._extractors)

    def for_path(self, path: str | PurePath) -> tuple[Extractor, ...]:
        """Every extractor that claims this path, in registration order."""
        pure = PurePath(path)
        suffix = pure.suffix.lower()
        filename = pure.name.lower()
        return tuple(
            extractor
            for extractor in self._extractors
            if suffix in extractor.suffixes or filename in extractor.filenames
        )

    def handles(self, path: str | PurePath) -> bool:
        return bool(self.for_path(path))

    def claimed_suffixes(self) -> frozenset[str]:
        """Union of every claimed suffix - used to filter a full-tree walk."""
        return frozenset().union(*(e.suffixes for e in self._extractors)) if self._extractors else frozenset()

    def claimed_filenames(self) -> frozenset[str]:
        return frozenset().union(*(e.filenames for e in self._extractors)) if self._extractors else frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        """Run every extractor that claims the path and concatenate the results.

        Duplicates are possible when two extractors see the same read; the
        comparison stage works on sets of names, so they are harmless.
        """
        usages: list[Usage] = []
        for extractor in self.for_path(relative_path):
            usages.extend(extractor.extract(source, relative_path))
        return usages
