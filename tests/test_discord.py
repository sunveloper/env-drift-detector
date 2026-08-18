import pytest

from env_drift.drift import compare
from env_drift.models import Usage
from env_drift.reporters.discord import (
    COLOR_FAIL,
    COLOR_OK,
    DiscordError,
    build_payload,
    validate_webhook_url,
)

VALID = "https://discord.com/api/webhooks/123456789/abcdefTOKEN"


def test_valid_webhook_url_is_accepted():
    assert validate_webhook_url(VALID) == VALID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "http://discord.com/api/webhooks/1/t",          # not https
        "https://evil.example.com/api/webhooks/1/t",     # wrong host
        "https://discord.com/api/oauth2/token",          # not a webhook path
    ],
)
def test_bad_webhook_urls_are_rejected(url):
    with pytest.raises(DiscordError):
        validate_webhook_url(url)


def test_error_message_never_leaks_the_url():
    secret = "https://evil.example.com/api/webhooks/1/SUPERSECRETTOKEN"
    with pytest.raises(DiscordError) as exc:
        validate_webhook_url(secret)
    assert "SUPERSECRETTOKEN" not in str(exc.value)


def test_payload_marks_missing_vars_as_failure():
    report = compare([Usage("APP_KEY", "app.py", 4)], set(), ignored=set(), commit="abc1234def")
    payload = build_payload(report)
    embed = payload["embeds"][0]
    assert embed["color"] == COLOR_FAIL
    assert "APP_KEY" in embed["fields"][0]["value"]
    assert "app.py:4" in embed["fields"][0]["value"]


def test_payload_is_green_when_clean():
    report = compare([Usage("TOKEN", "a.py", 1)], {"TOKEN"}, ignored=set())
    embed = build_payload(report)["embeds"][0]
    assert embed["color"] == COLOR_OK
    assert "fields" not in embed


def test_long_field_values_are_truncated_to_discord_limit():
    usages = [Usage(f"VAR_{i:04d}", "app.py", i) for i in range(400)]
    report = compare(usages, set(), ignored=set())
    field = build_payload(report)["embeds"][0]["fields"][0]
    assert len(field["value"]) <= 1024
