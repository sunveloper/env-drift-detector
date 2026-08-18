"""Tests for ``env-drift verify``.

The first section is the security boundary: no real value may appear in a report
or in the rendered output. Those tests exist to fail loudly if someone later adds
a value to the output "just for debugging".
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from env_drift.cli import main
from env_drift.verify import (
    Verdict,
    looks_like_placeholder,
    render_verify_report,
    verify_environment,
)

TEMPLATE = (
    "API_KEY=replace-with-your-key\n"
    "DATABASE_URL=postgres://user:pass@localhost/db\n"
    "PORT=3000\n"
)

SECRET = "sk_live_realproductionsecret"


# --- the security boundary --------------------------------------------------


def test_no_real_value_reaches_the_report():
    report = verify_environment(
        TEMPLATE,
        {"API_KEY": SECRET, "DATABASE_URL": SECRET, "PORT": SECRET},
    )
    assert SECRET not in repr(report)
    assert SECRET not in str(asdict(report))


def test_no_real_value_reaches_the_rendered_output():
    report = verify_environment(TEMPLATE, {"API_KEY": SECRET})
    assert SECRET not in render_verify_report(report)


def test_not_even_a_fragment_of_a_value_is_emitted():
    # Guards against a masked or truncated value being added later.
    report = verify_environment(TEMPLATE, {"API_KEY": SECRET})
    out = render_verify_report(report)
    for length in (3, 4, 6):
        assert SECRET[:length] not in out
        assert SECRET[-length:] not in out


def test_findings_expose_names_and_verdicts_only():
    report = verify_environment(TEMPLATE, {})
    for finding in report.findings:
        assert set(asdict(finding)) == {"name", "verdict"}


# --- placeholder recognition ------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "replace-with-your-key",
        "CHANGEME",
        "change_me",
        "your-token-here",
        "placeholder",
        "admin@example.com",
        "dummy",
        "FIXME",
        "TODO",
        "xxx",
        "<your-key>",
        "000000000000",
        "aaaaaaaaaa",
    ],
)
def test_stand_in_values_are_recognised(value):
    assert looks_like_placeholder(value) is True


@pytest.mark.parametrize(
    "value",
    ["3000", "INFO", "true", ".env.example", "redis://localhost", "utf-8", "en_US"],
)
def test_genuine_defaults_are_not_treated_as_placeholders(value):
    # A template may hold real defaults. Flagging an environment that keeps them
    # would make the command useless in projects that write good templates.
    assert looks_like_placeholder(value) is False


def test_empty_template_value_is_not_a_placeholder():
    # An empty value declares "no value needed", a statement about the variable.
    assert looks_like_placeholder("") is False


def test_dot_env_example_path_is_not_flagged():
    # Regression guard: matching bare "example" would catch this tool's own config.
    assert looks_like_placeholder(".env.example") is False


# --- classification ---------------------------------------------------------


def test_unset_variable_is_a_finding():
    report = verify_environment(TEMPLATE, {"DATABASE_URL": "x", "PORT": "8080"})
    assert report.unset == ("API_KEY",)


def test_blank_value_counts_as_unset():
    report = verify_environment(TEMPLATE, {"API_KEY": "   ", "DATABASE_URL": "x", "PORT": "1"})
    assert report.unset == ("API_KEY",)


def test_value_left_as_the_placeholder_is_a_finding():
    report = verify_environment(
        TEMPLATE,
        {"API_KEY": "replace-with-your-key", "DATABASE_URL": "x", "PORT": "1"},
    )
    assert report.still_placeholder == ("API_KEY",)


def test_keeping_a_genuine_default_is_not_a_finding():
    report = verify_environment(
        TEMPLATE,
        {"API_KEY": SECRET, "DATABASE_URL": "postgres://real/db", "PORT": "3000"},
    )
    assert report.has_findings is False


def test_strict_mode_flags_any_unchanged_value():
    report = verify_environment(
        TEMPLATE,
        {"API_KEY": SECRET, "DATABASE_URL": "postgres://real/db", "PORT": "3000"},
        strict_placeholder=True,
    )
    assert report.still_placeholder == ("PORT",)


def test_blank_template_entries_are_listed_as_optional_not_unset():
    report = verify_environment("OPTIONAL_ONE=\nAPI_KEY=replace-me\n", {"API_KEY": SECRET})
    assert report.optional == ("OPTIONAL_ONE",)
    assert report.has_findings is False


def test_extra_environment_variables_are_ignored():
    # The template defines the scope; the environment always has more than that.
    report = verify_environment(
        "API_KEY=replace-me\n", {"API_KEY": SECRET, "PATH": "/usr/bin", "HOME": "/root"}
    )
    assert report.checked == ("API_KEY",)


def test_findings_are_ordered_by_name():
    report = verify_environment("ZED=replace-me\nALPHA=replace-me\n", {})
    assert [f.name for f in report.findings] == ["ALPHA", "ZED"]


def test_verdicts_are_distinguished():
    report = verify_environment(TEMPLATE, {"API_KEY": "replace-with-your-key", "PORT": "1"})
    verdicts = {f.name: f.verdict for f in report.findings}
    assert verdicts == {
        "API_KEY": Verdict.STILL_PLACEHOLDER,
        "DATABASE_URL": Verdict.UNSET,
    }


# --- rendering --------------------------------------------------------------


def test_clean_environment_says_so():
    report = verify_environment("PORT=3000\n", {"PORT": "8080"})
    assert "OK - every documented variable has a real value." in render_verify_report(report)


def test_output_separates_the_two_verdicts():
    report = verify_environment(TEMPLATE, {"API_KEY": "replace-with-your-key", "PORT": "1"})
    out = render_verify_report(report)
    assert "NOT SET (1)" in out and "DATABASE_URL" in out
    assert "STILL THE TEMPLATE PLACEHOLDER (1)" in out and "API_KEY" in out


def test_optional_count_is_reported_on_a_clean_run():
    report = verify_environment("BLANK=\nPORT=3000\n", {"PORT": "1"})
    assert "1 variable(s) blank in the template" in render_verify_report(report)


# --- CLI --------------------------------------------------------------------


def write_template(tmp_path: Path, text: str = TEMPLATE) -> None:
    (tmp_path / ".env.example").write_text(text, encoding="utf-8")


def test_cli_verify_flags_a_copied_but_unedited_env_file(tmp_path: Path, capsys):
    write_template(tmp_path)
    (tmp_path / ".env").write_text(TEMPLATE, encoding="utf-8")  # copied verbatim

    exit_code = main(["verify", "--repo", str(tmp_path), "--env-file", ".env"])

    assert exit_code == 1
    assert "API_KEY" in capsys.readouterr().out


def test_cli_verify_passes_on_a_filled_in_env_file(tmp_path: Path, capsys):
    write_template(tmp_path)
    (tmp_path / ".env").write_text(
        f"API_KEY={SECRET}\nDATABASE_URL=postgres://real/db\nPORT=3000\n", encoding="utf-8"
    )

    assert main(["verify", "--repo", str(tmp_path), "--env-file", ".env"]) == 0
    assert SECRET not in capsys.readouterr().out


def test_cli_verify_reads_the_process_environment_by_default(tmp_path: Path, monkeypatch, capsys):
    write_template(tmp_path, "API_KEY=replace-me\n")
    monkeypatch.setenv("API_KEY", SECRET)

    assert main(["verify", "--repo", str(tmp_path)]) == 0
    assert "process environment" in capsys.readouterr().out


def test_cli_verify_no_fail_reports_without_failing(tmp_path: Path):
    write_template(tmp_path)
    assert main(["verify", "--repo", str(tmp_path), "--env-file", ".env", "--no-fail"]) == 2
    (tmp_path / ".env").write_text("", encoding="utf-8")
    assert main(["verify", "--repo", str(tmp_path), "--env-file", ".env", "--no-fail"]) == 0


def test_cli_verify_missing_template_is_a_tool_error(tmp_path: Path, capsys):
    assert main(["verify", "--repo", str(tmp_path)]) == 2
    assert "env template not found" in capsys.readouterr().err


def test_cli_verify_missing_env_file_is_a_tool_error(tmp_path: Path, capsys):
    write_template(tmp_path)
    assert main(["verify", "--repo", str(tmp_path), "--env-file", "nope.env"]) == 2
    assert "env file not found" in capsys.readouterr().err


def test_verify_parser_offers_no_webhook_option():
    # The absence of a Discord path is a security property, not an oversight.
    from env_drift.cli import build_verify_parser

    options = {action.dest for action in build_verify_parser()._actions}
    assert "webhook" not in options
