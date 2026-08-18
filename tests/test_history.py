"""Tests for comparing the env template against its previous revision.

Real values are never involved - only the committed template, whose values are
placeholders. The tests below double as the record of that boundary.
"""

from __future__ import annotations

from env_drift.drift import compare
from env_drift.history import PlaceholderChange, compare_template_revisions
from env_drift.models import Usage
from env_drift.reporters.console import render_console
from env_drift.reporters.discord import COLOR_FAIL, COLOR_OK, COLOR_WARN, build_payload
from env_drift.template import parse_template_entries


# --- template parsing -------------------------------------------------------


def test_entries_capture_names_and_placeholders():
    assert parse_template_entries("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_quotes_are_stripped_so_requoting_is_not_a_change():
    assert parse_template_entries('A="x"\n') == parse_template_entries("A=x\n")


def test_inline_comment_is_not_part_of_the_value():
    assert parse_template_entries("A=x  # explain\n") == {"A": "x"}


def test_hash_without_preceding_space_stays_in_the_value():
    # A '#' inside a URL fragment or password placeholder is part of the value.
    assert parse_template_entries("A=pa#ss\n") == {"A": "pa#ss"}


def test_empty_value_is_allowed():
    assert parse_template_entries("A=\n") == {"A": ""}


def test_export_prefix_and_last_declaration_wins():
    assert parse_template_entries("export A=1\nA=2\n") == {"A": "2"}


# --- revision comparison ----------------------------------------------------


def test_added_variable_is_detected():
    history = compare_template_revisions("A=1\nB=2\n", "A=1\n", ref="HEAD^")
    assert history.added == ("B",)
    assert history.removed == ()
    assert history.compared_against == "HEAD^"


def test_removed_variable_is_detected():
    history = compare_template_revisions("A=1\n", "A=1\nB=2\n")
    assert history.removed == ("B",)


def test_changed_placeholder_is_detected():
    history = compare_template_revisions("URL=rediss://host\n", "URL=redis://host\n")
    assert history.placeholder_changed == (
        PlaceholderChange(name="URL", before="redis://host", after="rediss://host"),
    )


def test_identical_revisions_report_nothing():
    history = compare_template_revisions("A=1\n", "A=1\n")
    assert history.has_changes is False


def test_comment_only_edit_is_not_a_change():
    history = compare_template_revisions("# new note\nA=1\n", "A=1\n")
    assert history.has_changes is False


def test_removal_alone_does_not_ask_for_local_action():
    # A stale entry in someone's .env is harmless; a missing one is not.
    history = compare_template_revisions("A=1\n", "A=1\nB=2\n")
    assert history.has_changes is True
    assert history.needs_local_action is False


def test_addition_asks_for_local_action():
    assert compare_template_revisions("A=1\nB=2\n", "A=1\n").needs_local_action is True


def test_changed_placeholder_asks_for_local_action():
    history = compare_template_revisions("A=2\n", "A=1\n")
    assert history.needs_local_action is True


def test_added_and_removed_are_sorted():
    history = compare_template_revisions("Z=1\nA=1\n", "Y=1\nB=1\n")
    assert history.added == ("A", "Z")
    assert history.removed == ("B", "Y")


# --- reporting --------------------------------------------------------------


def report_with(history, **kwargs):
    return compare([Usage("KNOWN", "a.py", 1)], {"KNOWN"}, ignored=set(), history=history, **kwargs)


def test_console_spells_out_what_to_do_per_change():
    history = compare_template_revisions("A=1\nNEW=x\n", "A=1\nOLD=y\n", ref="abc1234")
    out = render_console(report_with(history))
    assert "TEMPLATE CHANGED since abc1234" in out
    assert "+ NEW  (add it to your .env)" in out
    assert "- OLD" in out
    assert "refresh their local .env" in out


def test_console_shows_the_placeholder_transition():
    history = compare_template_revisions("URL=rediss://h\n", "URL=redis://h\n")
    assert '"redis://h" -> "rediss://h"' in render_console(report_with(history))


def test_console_omits_the_section_when_nothing_changed():
    assert "TEMPLATE CHANGED" not in render_console(report_with(None))


def test_discord_warns_when_only_the_template_changed():
    # No drift, but every developer has to edit their own .env - not a silent pass.
    history = compare_template_revisions("KNOWN=1\nNEW=x\n", "KNOWN=1\n")
    embed = build_payload(report_with(history))["embeds"][0]
    assert embed["color"] == COLOR_WARN
    assert "update your .env" in embed["title"]
    assert "add it to your `.env`" in embed["fields"][0]["value"]


def test_discord_stays_green_for_a_removal_only_change():
    history = compare_template_revisions("KNOWN=1\n", "KNOWN=1\nOLD=2\n")
    embed = build_payload(report_with(history))["embeds"][0]
    assert embed["color"] == COLOR_OK
    assert "no longer used" in embed["fields"][0]["value"]


def test_missing_variable_still_outranks_a_template_change():
    history = compare_template_revisions("KNOWN=1\nNEW=x\n", "KNOWN=1\n")
    report = compare([Usage("SECRET", "a.py", 1)], set(), ignored=set(), history=history)
    embed = build_payload(report)["embeds"][0]
    assert embed["color"] == COLOR_FAIL


def test_template_change_alone_is_noteworthy_but_does_not_fail_the_build():
    history = compare_template_revisions("KNOWN=1\nNEW=x\n", "KNOWN=1\n")
    report = report_with(history)
    assert report.is_noteworthy is True
    assert report.has_drift is False
    assert report.fails_build is False
