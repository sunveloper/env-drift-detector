"""Tests for the required / optional split.

A read that supplies its own fallback cannot break a deployment by being unset,
so it must be reported without failing the build. These tests pin that down at
every layer: scanner detection, classification, and the two reporters.
"""

from __future__ import annotations

from env_drift.drift import compare
from env_drift.models import Usage
from env_drift.reporters.console import render_console
from env_drift.reporters.discord import COLOR_FAIL, COLOR_OK, COLOR_WARN, build_payload
from env_drift.scanner import scan_javascript, scan_python


def by_name(usages):
    return {u.name: u for u in usages}


# --- scanner: Python ---------------------------------------------------------


def test_python_second_argument_marks_the_read_optional():
    usages = by_name(
        scan_python(
            "import os\n"
            "port = os.getenv('PORT', '8000')\n"
            "key = os.getenv('SECRET_KEY')\n",
            "app.py",
        )
    )
    assert usages["PORT"].optional is True
    assert usages["PORT"].default == "8000"
    assert usages["SECRET_KEY"].optional is False
    assert usages["SECRET_KEY"].default is None


def test_explicit_none_default_is_still_required():
    # os.getenv("X", None) says "no default" just as clearly as omitting it.
    usage = by_name(scan_python("import os\nos.getenv('X', None)\n", "a.py"))["X"]
    assert usage.optional is False


def test_environ_get_with_default_is_optional():
    usage = by_name(scan_python("import os\nos.environ.get('LEVEL', 'INFO')\n", "a.py"))
    assert usage["LEVEL"].optional is True
    assert usage["LEVEL"].default == "INFO"


def test_subscript_access_is_always_required():
    # os.environ["X"] raises KeyError when unset - there is no fallback path.
    usage = by_name(scan_python("import os\nos.environ['X']\n", "a.py"))["X"]
    assert usage.optional is False


def test_setdefault_is_optional_by_construction():
    usage = by_name(scan_python("from os import environ\nenviron.setdefault('A', '1')\n", "a.py"))
    assert usage["A"].optional is True


def test_non_literal_default_is_optional_without_a_quotable_value():
    source = "import os\ndef pick(): return '1'\nos.getenv('X', pick())\n"
    usage = by_name(scan_python(source, "a.py"))["X"]
    assert usage.optional is True
    assert usage.default is None


def test_numeric_default_is_rendered_as_text():
    usage = by_name(scan_python("import os\nos.getenv('PORT', 8000)\n", "a.py"))["PORT"]
    assert usage.default == "8000"


# --- scanner: JavaScript ----------------------------------------------------


def test_js_nullish_and_or_fallbacks_are_optional():
    usages = by_name(
        scan_javascript(
            "const a = process.env.PORT ?? '3000';\n"
            "const b = process.env.LEVEL || \"info\";\n"
            "const c = process.env.SECRET;\n",
            "app.ts",
        )
    )
    assert (usages["PORT"].optional, usages["PORT"].default) == (True, "3000")
    assert (usages["LEVEL"].optional, usages["LEVEL"].default) == (True, "info")
    assert usages["SECRET"].optional is False


def test_js_numeric_and_boolean_defaults_are_captured():
    usages = by_name(
        scan_javascript(
            "const a = process.env.PORT ?? 3000;\nconst b = process.env.DEBUG ?? false;\n",
            "a.js",
        )
    )
    assert usages["PORT"].default == "3000"
    assert usages["DEBUG"].default == "false"


def test_js_chained_fallback_still_finds_both_variables():
    usages = by_name(scan_javascript("const x = process.env.A || process.env.B;\n", "a.js"))
    assert set(usages) == {"A", "B"}


# --- classification ---------------------------------------------------------


def test_optional_undocumented_is_separated_from_missing():
    usages = [
        Usage("SECRET_KEY", "a.py", 1, optional=False),
        Usage("LOG_LEVEL", "a.py", 2, optional=True, default="INFO"),
    ]
    report = compare(usages, set(), ignored=set())
    assert report.missing == ("SECRET_KEY",)
    assert report.optional_undocumented == ("LOG_LEVEL",)


def test_optional_undocumented_does_not_fail_the_build():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 1, optional=True, default="INFO")], set(), ignored=set()
    )
    assert report.fails_build is False
    assert report.has_drift is True  # still reported


def test_missing_fails_the_build():
    report = compare([Usage("SECRET", "a.py", 1)], set(), ignored=set())
    assert report.fails_build is True


def test_one_required_read_outweighs_an_optional_one():
    # If any call site cannot cope without the value, the service can still break.
    usages = [
        Usage("TOKEN", "a.py", 1, optional=True, default="x"),
        Usage("TOKEN", "b.py", 9, optional=False),
    ]
    report = compare(usages, set(), ignored=set())
    assert report.missing == ("TOKEN",)
    assert report.optional_undocumented == ()


def test_documented_optional_variable_is_clean():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 1, optional=True, default="INFO")],
        {"LOG_LEVEL"},
        ignored=set(),
    )
    assert not report.has_drift


def test_ignored_names_are_excluded_even_when_optional():
    report = compare(
        [Usage("NODE_ENV", "a.js", 1, optional=True, default="dev")], set(), ignored={"NODE_ENV"}
    )
    assert report.optional_undocumented == ()


def test_optional_usage_counts_as_used_for_unused_detection():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 1, optional=True)], {"LOG_LEVEL"}, ignored=set()
    )
    assert report.unused == ()


# --- reporters --------------------------------------------------------------


def test_console_labels_the_optional_section_as_non_failing():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 4, optional=True, default="INFO")], set(), ignored=set()
    )
    out = render_console(report)
    assert "does not fail the build" in out
    assert 'default: "INFO"' in out
    assert "a.py:4" in out
    assert "MISSING" not in out


def test_discord_uses_yellow_for_optional_only_drift():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 1, optional=True, default="INFO")], set(), ignored=set()
    )
    embed = build_payload(report)["embeds"][0]
    assert embed["color"] == COLOR_WARN
    assert "does not fail the build" in embed["fields"][0]["name"]
    assert "default `INFO`" in embed["fields"][0]["value"]


def test_discord_stays_red_when_both_kinds_are_present():
    usages = [
        Usage("SECRET", "a.py", 1),
        Usage("LOG_LEVEL", "a.py", 2, optional=True, default="INFO"),
    ]
    embed = build_payload(compare(usages, set(), ignored=set()))["embeds"][0]
    assert embed["color"] == COLOR_FAIL
    assert len(embed["fields"]) == 2


def test_discord_green_when_everything_is_documented():
    report = compare(
        [Usage("LOG_LEVEL", "a.py", 1, optional=True)], {"LOG_LEVEL"}, ignored=set()
    )
    assert build_payload(report)["embeds"][0]["color"] == COLOR_OK
