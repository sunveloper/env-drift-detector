"""Walk files and hand each one to whichever extractors claim it.

All language knowledge lives in ``extractors/``. This module only decides *which*
files to look at and turns paths into text - so adding a stack never touches it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .extractors import Registry, default_registry
from .extractors.javascript import JavaScriptExtractor
from .extractors.nest import NestConfigExtractor
from .extractors.python_ast import PythonExtractor
from .models import Usage

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "site-packages",
    }
)


def scan_file(path: Path, root: Path, registry: Registry = default_registry) -> list[Usage]:
    """Scan one file with every extractor that claims it.

    An unreadable file yields nothing rather than raising: a CI run should report
    the drift it can see, not abort on one bad file.
    """
    relative_path = _relative(path, root)
    if not registry.handles(relative_path):
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return registry.extract(source, relative_path)


def scan_paths(
    paths: Iterable[Path], root: Path, registry: Registry = default_registry
) -> list[Usage]:
    """Scan an explicit list of files - the git-diff driven entry point."""
    usages: list[Usage] = []
    for path in paths:
        if path.is_file():
            usages.extend(scan_file(path, root, registry))
    return usages


def iter_source_files(
    root: Path,
    excluded_dirs: Sequence[str] | None = None,
    registry: Registry = default_registry,
) -> list[Path]:
    """Walk the tree for files some extractor claims - the ``--all`` entry point."""
    excluded = set(excluded_dirs) if excluded_dirs is not None else set(DEFAULT_EXCLUDED_DIRS)
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if excluded.intersection(relative.parts[:-1]):
            continue
        if not registry.handles(relative.as_posix()):
            continue
        found.append(path)
    return found


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- convenience wrappers ----------------------------------------------------
# Single-extractor entry points. Handy for testing one language in isolation and
# for callers that already know what they are holding.

def scan_python(source: str, relative_path: str) -> list[Usage]:
    return PythonExtractor().extract(source, relative_path)


def scan_javascript(source: str, relative_path: str) -> list[Usage]:
    return JavaScriptExtractor().extract(source, relative_path)


def scan_nest(source: str, relative_path: str) -> list[Usage]:
    return NestConfigExtractor().extract(source, relative_path)


# Kept for callers that filtered on these before the registry existed.
PYTHON_SUFFIXES = PythonExtractor.suffixes
JS_SUFFIXES = JavaScriptExtractor.suffixes
SUPPORTED_SUFFIXES = default_registry.claimed_suffixes()
