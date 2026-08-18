"""Tests for the extractor registry.

The registry is what lets a stack be added without editing the scanner, so the
behaviour worth pinning is the dispatch: who claims a file, what happens when
two extractors claim the same one, and what happens when nobody does.
"""

from __future__ import annotations

from pathlib import Path

from env_drift.extractors import (
    DEFAULT_EXTRACTORS,
    JavaScriptExtractor,
    NestConfigExtractor,
    PythonExtractor,
    Registry,
    default_registry,
)
from env_drift.models import Usage
from env_drift.scanner import iter_source_files, scan_file


class _TomlExtractor:
    """A stand-in for a future stack, to prove registration needs nothing else.

    Uses .toml because no default extractor claims it - that keeps the "before
    registration nothing handles this" half of each test meaningful.
    """

    name = "fake-toml"
    suffixes = frozenset({".toml"})
    filenames = frozenset({"pyproject.cfg"})

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        return [Usage(name="FROM_TOML", file=relative_path, line=1)]


def test_suffix_claim_selects_the_right_extractor():
    names = [e.name for e in default_registry.for_path("src/app.py")]
    assert names == ["python"]


def test_java_is_claimed_by_both_placeholder_and_java_extractors():
    # A Spring class can read a @Value("${VAR}") placeholder and call
    # System.getenv in the same file.
    names = [e.name for e in default_registry.for_path("src/App.java")]
    assert names == ["property-placeholder", "java"]


def test_property_files_are_claimed_by_the_placeholder_extractor():
    for path in ("application.yml", "application-prod.properties", "compose.yaml"):
        assert [e.name for e in default_registry.for_path(path)] == ["property-placeholder"]


def test_typescript_is_claimed_by_both_js_and_nest():
    # A Nest service commonly uses process.env and ConfigService in one file.
    names = [e.name for e in default_registry.for_path("src/app.service.ts")]
    assert names == ["javascript", "nest-config"]


def test_unclaimed_file_yields_no_extractors():
    assert default_registry.for_path("README.md") == ()
    assert default_registry.handles("README.md") is False


def test_filename_claim_works_without_a_matching_suffix():
    registry = Registry([_TomlExtractor()])
    assert registry.handles("config/pyproject.cfg") is True
    assert registry.handles("notes.txt") is False


def test_extract_concatenates_results_from_every_claiming_extractor():
    source = "const a = process.env.FROM_ENV;\nconst b = config.get('FROM_CONFIG');\n"
    names = {u.name for u in default_registry.extract(source, "app.service.ts")}
    assert names == {"FROM_ENV", "FROM_CONFIG"}


def test_register_adds_an_extractor_without_touching_the_defaults():
    registry = Registry(list(DEFAULT_EXTRACTORS))
    registry.register(_TomlExtractor())

    assert registry.handles("settings.toml") is True
    assert default_registry.handles("settings.toml") is False  # defaults untouched


def test_claimed_suffixes_is_the_union_over_extractors():
    registry = Registry([PythonExtractor(), JavaScriptExtractor()])
    assert registry.claimed_suffixes() == PythonExtractor.suffixes | JavaScriptExtractor.suffixes


def test_empty_registry_claims_nothing():
    registry = Registry()
    assert registry.claimed_suffixes() == frozenset()
    assert registry.handles("app.py") is False


def test_nest_and_js_extractors_share_the_same_suffixes():
    # If these diverge, a Nest file could be scanned by only one of them.
    assert NestConfigExtractor.suffixes == JavaScriptExtractor.suffixes


def test_scan_file_honours_a_custom_registry(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("anything", encoding="utf-8")

    assert scan_file(target, tmp_path) == []  # default registry ignores .toml
    usages = scan_file(target, tmp_path, Registry([_TomlExtractor()]))
    assert [u.name for u in usages] == ["FROM_TOML"]


def test_iter_source_files_follows_the_registry(tmp_path: Path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "config.toml").write_text("", encoding="utf-8")

    assert [p.name for p in iter_source_files(tmp_path)] == ["app.py"]

    registry = Registry([PythonExtractor(), _TomlExtractor()])
    found = sorted(p.name for p in iter_source_files(tmp_path, registry=registry))
    assert found == ["app.py", "config.toml"]
