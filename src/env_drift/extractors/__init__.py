"""Per-stack extractors and the default registry.

To support a new stack: write a module exposing a class that satisfies
``Extractor``, then append an instance to ``DEFAULT_EXTRACTORS`` below. Nothing
else in the codebase needs to change.
"""

from __future__ import annotations

from .base import NO_FALLBACK, Extractor, Registry
from .java import JavaExtractor
from .javascript import JavaScriptExtractor
from .nest import NestConfigExtractor
from .property_placeholder import PropertyPlaceholderExtractor
from .python_ast import PythonExtractor

DEFAULT_EXTRACTORS: list[Extractor] = [
    PythonExtractor(),
    JavaScriptExtractor(),
    # Runs over the same .ts/.js files as JavaScriptExtractor. A Nest service
    # commonly uses both process.env and ConfigService, so both must be scanned.
    NestConfigExtractor(),
    # Claims .yml / .yaml / .properties, and also .java / .kt for @Value("${VAR}").
    PropertyPlaceholderExtractor(),
    # Shares .java / .kt with the extractor above: a Spring class can read a
    # property placeholder and call System.getenv in the same file.
    JavaExtractor(),
]

default_registry = Registry(DEFAULT_EXTRACTORS)

__all__ = [
    "DEFAULT_EXTRACTORS",
    "Extractor",
    "JavaExtractor",
    "JavaScriptExtractor",
    "NO_FALLBACK",
    "NestConfigExtractor",
    "PropertyPlaceholderExtractor",
    "PythonExtractor",
    "Registry",
    "default_registry",
]
