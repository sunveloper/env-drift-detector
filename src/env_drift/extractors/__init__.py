"""Per-stack extractors and the default registry.

To support a new stack: write a module exposing a class that satisfies
``Extractor``, then append an instance to ``DEFAULT_EXTRACTORS`` below. Nothing
else in the codebase needs to change.
"""

from __future__ import annotations

from .base import NO_FALLBACK, Extractor, Registry
from .javascript import JavaScriptExtractor
from .nest import NestConfigExtractor
from .python_ast import PythonExtractor

DEFAULT_EXTRACTORS: list[Extractor] = [
    PythonExtractor(),
    JavaScriptExtractor(),
    # Runs over the same .ts/.js files as JavaScriptExtractor. A Nest service
    # commonly uses both process.env and ConfigService, so both must be scanned.
    NestConfigExtractor(),
]

default_registry = Registry(DEFAULT_EXTRACTORS)

__all__ = [
    "DEFAULT_EXTRACTORS",
    "Extractor",
    "JavaScriptExtractor",
    "NO_FALLBACK",
    "NestConfigExtractor",
    "PythonExtractor",
    "Registry",
    "default_registry",
]
