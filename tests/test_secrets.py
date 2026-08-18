"""Tests for credential-shape detection and redaction.

Two values in a report come from the repository: a fallback literal in the source
and a placeholder in the template. Both are normally printed in full. The
exception is a value that should never have been committed, and the leak-guard
section below is what keeps that exception enforced rather than merely intended.
"""

from __future__ import annotations

import pytest

from env_drift.drift import compare
from env_drift.history import compare_template_revisions
from env_drift.models import Usage
from env_drift.reporters.console import render_console
from env_drift.reporters.discord import COLOR_FAIL, build_payload
from env_drift.secrets import REDACTED, looks_like_secret, safe, shannon_entropy

LIVE_KEY = "sk_live_51H8sQvKZvKuAbCdEfGhIjKlMn"
OPAQUE = "aG7kQ2pXvR9mTz4LbN8sYw1EjD6uFc0H"


# --- leak guard -------------------------------------------------------------


def test_credential_code_default_is_not_printed_to_the_console():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    out = render_console(compare(usages, set(), ignored=set()))
    assert LIVE_KEY not in out
    assert REDACTED in out


def test_credential_code_default_is_not_sent_to_discord():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    payload = build_payload(compare(usages, set(), ignored=set()))
    assert LIVE_KEY not in str(payload)


def test_credential_in_a_changed_placeholder_is_not_printed():
    history = compare_template_revisions(f"API_KEY={LIVE_KEY}\n", "API_KEY=sk_live_old\n")
    report = compare([Usage("KNOWN", "a.py", 1)], {"KNOWN"}, ignored=set(), history=history)
    assert LIVE_KEY not in render_console(report)
    assert LIVE_KEY not in str(build_payload(report))


def test_no_fragment_of_a_credential_survives():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    out = render_console(compare(usages, set(), ignored=set()))
    for length in (8, 12, 16):
        assert LIVE_KEY[:length] not in out
        assert LIVE_KEY[-length:] not in out


def test_committed_secret_findings_carry_no_value():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    report = compare(usages, set(), ignored=set())
    for secret in report.committed_secrets:
        assert LIVE_KEY not in str(secret)


# --- shape detection: positives ---------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "sk_live_51H8sQvKZvKuAbCdEfGh",
        "sk_test_51H8sQvKZvKuAbCdEfGh",
        "rk_live_51H8sQvKZvKuAbCdEfGh",
        "ghp_16CharactersMinimumHere00",
        "github_pat_11ABCDEFG0abcdefghij",
        "xoxb-123456789012-abcdefghij",
        "AKIA1234567890ABCDEF",
        "AIzaSyA1234567890abcdefghijklmnopqrstuv",
        "SG.aBcDeFgHiJkLmNoP.qRsTuVwXyZ",
        "glpat-aBcDeFgHiJkLmNoPqRsT",
        "-----BEGIN RSA PRIVATE KEY-----",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc",
        OPAQUE,
        "postgres://admin:hunter2ButLonger@db.internal:5432/app",
    ],
)
def test_credential_shapes_are_detected(value):
    assert looks_like_secret(value) is True


# --- shape detection: negatives ---------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "3000",
        "INFO",
        "true",
        "localhost",
        ".env.example",
        "redis://localhost",
        "postgres://localhost:5432/app",  # no password
        "PATH,HOME,PYTHONPATH,NODE_ENV",
        "https://discord.com/api/webhooks/000/replace-with-your-webhook-token",
    ],
)
def test_ordinary_values_are_left_alone(value):
    assert looks_like_secret(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "sk_live_replace_with_your_key",
        "changeme-changeme-changeme-changeme",
        "your-super-secret-key-goes-here-x",
        "postgres://admin:changeme@localhost/db",
        "AIzaSyPLACEHOLDERPLACEHOLDERPLACEHOLDER",
    ],
)
def test_self_declared_placeholders_stay_visible(value):
    # Seeing the placeholder is the point of the report, however random it looks.
    assert looks_like_secret(value) is False


def test_aws_documentation_key_is_treated_as_a_stand_in():
    # AKIAIOSFODNN7EXAMPLE is the key AWS uses in its own docs, so it appears in
    # countless tutorials and templates. The "EXAMPLE" marker keeps it visible.
    assert looks_like_secret("AKIAIOSFODNN7EXAMPLE") is False


def test_none_is_not_a_secret():
    assert looks_like_secret(None) is False
    assert safe(None) is None


def test_short_random_strings_are_not_flagged():
    # Under the length floor: too many ordinary values would trip otherwise.
    assert looks_like_secret("aG7kQ2pX") is False


def test_long_low_entropy_strings_are_not_flagged():
    assert looks_like_secret("a" * 40) is False


def test_entropy_ranks_random_above_prose():
    assert shannon_entropy(OPAQUE) > shannon_entropy("the quick brown fox")


def test_safe_passes_ordinary_values_through_unchanged():
    assert safe("3000") == "3000"
    assert safe(LIVE_KEY) == REDACTED


# --- reporting as a finding -------------------------------------------------


def test_a_committed_credential_fails_the_build():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    report = compare(usages, {"API_KEY"}, ignored=set())
    assert report.fails_build is True
    assert report.is_noteworthy is True


def test_the_finding_points_at_the_origin():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    secret = compare(usages, {"API_KEY"}, ignored=set()).committed_secrets[0]
    assert (secret.name, secret.where, secret.kind) == ("API_KEY", "app.py:12", "code default")


def test_a_credential_in_the_template_is_found():
    report = compare([], set(), ignored=set(), template_entries={"API_KEY": LIVE_KEY})
    secret = report.committed_secrets[0]
    assert (secret.name, secret.kind) == ("API_KEY", "template placeholder")


def test_discord_puts_the_credential_first_and_red():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    embed = build_payload(compare(usages, {"API_KEY"}, ignored=set()))["embeds"][0]
    assert embed["color"] == COLOR_FAIL
    assert "Committed credential" in embed["title"]
    assert "rotate it" in embed["fields"][0]["name"]


def test_console_tells_the_reader_to_rotate_then_remove():
    usages = [Usage("API_KEY", "app.py", 12, optional=True, default=LIVE_KEY)]
    out = render_console(compare(usages, {"API_KEY"}, ignored=set()))
    assert "COMMITTED CREDENTIAL (1)" in out
    assert "rotate the value, then remove it from the repository" in out
    assert "app.py:12" in out


def test_one_variable_read_twice_produces_one_finding_per_location():
    usages = [
        Usage("API_KEY", "a.py", 1, optional=True, default=LIVE_KEY),
        Usage("API_KEY", "a.py", 1, optional=True, default=LIVE_KEY),
        Usage("API_KEY", "b.py", 5, optional=True, default=LIVE_KEY),
    ]
    report = compare(usages, {"API_KEY"}, ignored=set())
    assert [s.where for s in report.committed_secrets] == ["a.py:1", "b.py:5"]


def test_ignored_names_are_not_reported_as_committed_secrets():
    usages = [Usage("API_KEY", "a.py", 1, optional=True, default=LIVE_KEY)]
    report = compare(usages, set(), ignored={"API_KEY"})
    assert report.committed_secrets == ()


def test_a_clean_report_has_no_credential_findings():
    usages = [Usage("PORT", "a.py", 1, optional=True, default="8000")]
    report = compare(usages, {"PORT"}, ignored=set())
    assert report.committed_secrets == ()
    assert report.fails_build is False
