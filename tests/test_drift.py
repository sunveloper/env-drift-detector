from env_drift.drift import compare
from env_drift.models import Usage
from env_drift.template import parse_template_text


def usage(name, file="app.py", line=1):
    return Usage(name=name, file=file, line=line)


def test_missing_variable_is_reported():
    report = compare([usage("NEW_TOKEN")], {"OLD_TOKEN"}, ignored=set())
    assert report.missing == ("NEW_TOKEN",)
    assert report.has_drift


def test_documented_variable_is_clean():
    report = compare([usage("TOKEN")], {"TOKEN"}, ignored=set())
    assert report.missing == ()
    assert report.unused == ()
    assert not report.has_drift


def test_unused_template_entry_is_reported_on_full_scan():
    report = compare([usage("TOKEN")], {"TOKEN", "STALE"}, ignored=set())
    assert report.unused == ("STALE",)


def test_unused_is_suppressed_in_diff_mode():
    # Only changed files were scanned, so absent template entries prove nothing.
    report = compare([usage("TOKEN")], {"TOKEN", "OTHER"}, ignored=set(), detect_unused=False)
    assert report.unused == ()


def test_ignored_names_are_excluded_both_ways():
    report = compare([usage("PATH"), usage("APP_KEY")], {"PATH"}, ignored={"PATH"})
    assert report.missing == ("APP_KEY",)
    assert report.unused == ()


def test_default_ignore_list_applies_when_none_passed():
    report = compare([usage("PATH")], set())
    assert report.missing == ()


def test_missing_names_are_sorted_for_stable_output():
    report = compare([usage("ZED"), usage("ALPHA")], set(), ignored=set())
    assert report.missing == ("ALPHA", "ZED")


def test_locations_deduplicate_repeated_reads():
    usages = [usage("T", "a.py", 3), usage("T", "a.py", 3), usage("T", "b.py", 9)]
    report = compare(usages, set(), ignored=set())
    assert report.locations_for("T") == ("a.py:3", "b.py:9")


def test_template_parser_reads_keys_only():
    text = """
# comment
FOO=bar
export BAZ=qux

  SPACED = value
not-a-var
"""
    assert parse_template_text(text) == {"FOO", "BAZ", "SPACED"}
