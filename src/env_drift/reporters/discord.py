"""Post a drift report to a Discord incoming webhook.

Security notes:
  * The webhook URL is a credential. It is read from the environment, never
    logged, and never echoed back into the report body.
  * The destination host is validated against Discord's own domains, so a
    tampered environment variable cannot turn this tool into an exfiltration
    channel for source-file paths.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..models import DriftReport

ALLOWED_HOSTS = frozenset({"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"})

# Discord embed limits. Exceeding any of these makes the API reject the message.
_MAX_FIELD_VALUE = 1024
_MAX_DESCRIPTION = 4096
_MAX_LOCATIONS_PER_VAR = 2

COLOR_FAIL = 0xE74C3C
COLOR_WARN = 0xF1C40F
COLOR_OK = 0x2ECC71


class DiscordError(RuntimeError):
    """Raised when the webhook URL is unusable or Discord rejects the request."""


def validate_webhook_url(url: str) -> str:
    """Return the URL if it is a well-formed Discord webhook, else raise.

    The error message deliberately omits the URL so a malformed secret is never
    written to a CI log.
    """
    if not url or not url.strip():
        raise DiscordError("DISCORD_WEBHOOK_URL is empty")

    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise DiscordError("DISCORD_WEBHOOK_URL must use https")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise DiscordError(
            "DISCORD_WEBHOOK_URL host is not a Discord domain "
            f"(allowed: {', '.join(sorted(ALLOWED_HOSTS))})"
        )
    if "/api/webhooks/" not in parsed.path:
        raise DiscordError("DISCORD_WEBHOOK_URL does not look like a webhook endpoint")
    return url.strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 4].rstrip() + "\n..."


def _usage_field(report: DriftReport, names: tuple[str, ...], *, show_default: bool) -> str:
    lines: list[str] = []
    for name in names:
        locations = report.locations_for(name)
        shown = ", ".join(f"`{loc}`" for loc in locations[:_MAX_LOCATIONS_PER_VAR])
        extra = len(locations) - _MAX_LOCATIONS_PER_VAR
        if extra > 0:
            shown += f" +{extra}"

        label = f"**{name}**"
        if show_default:
            default = report.default_for(name)
            if default is not None:
                label += f" (default `{default}`)"
        lines.append(f"• {label} — {shown}" if shown else f"• {label}")
    return _truncate("\n".join(lines), _MAX_FIELD_VALUE)


def _history_field(report: DriftReport) -> str:
    """Template changes, phrased as what each developer has to do about them."""
    history = report.history
    if history is None or not history.has_changes:
        return ""

    lines: list[str] = []
    for name in history.added:
        lines.append(f"➕ **{name}** — add it to your `.env`")
    for name in history.removed:
        lines.append(f"➖ **{name}** — no longer used, safe to drop")
    for change in history.placeholder_changed:
        lines.append(
            f"✏️ **{change.name}** — placeholder `{change.before}` → `{change.after}`"
        )
    if history.needs_local_action:
        lines.append("_Everyone should refresh their local `.env`._")
    return _truncate("\n".join(lines), _MAX_FIELD_VALUE)


def build_payload(report: DriftReport, *, detect_unused: bool = True) -> dict:
    """Render the report as a Discord webhook JSON body.

    Red is reserved for the build-breaking case. A variable that is undocumented
    but has a default, or a stale template entry, is yellow: worth fixing, not
    worth blocking a merge.
    """
    if report.missing:
        color, title = COLOR_FAIL, "Env drift: variables missing from template"
    elif report.optional_undocumented:
        color, title = COLOR_WARN, "Env drift: undocumented variables with defaults"
    elif report.unused and detect_unused:
        color, title = COLOR_WARN, "Env drift: template has stale variables"
    elif report.history is not None and report.history.needs_local_action:
        # No drift, but everyone has to touch their own .env - not a silent pass.
        color, title = COLOR_WARN, "Env template changed — update your .env"
    else:
        color, title = COLOR_OK, "Env check passed"

    description_parts = []
    if report.repo:
        description_parts.append(f"**Repo:** `{report.repo}`")
    if report.commit:
        subject = report.commit_subject or "(no subject)"
        description_parts.append(f"**Commit:** `{report.commit[:8]}` {subject}")
    description_parts.append(
        f"**Scanned:** {len(report.scanned_files)} changed file(s) "
        f"against `{report.template_path}`"
    )

    embed: dict = {
        "title": title,
        "description": _truncate("\n".join(description_parts), _MAX_DESCRIPTION),
        "color": color,
    }

    fields: list[dict] = []
    if report.missing:
        fields.append(
            {
                "name": f"Missing from {report.template_path} ({len(report.missing)})",
                "value": _usage_field(report, report.missing, show_default=False),
                "inline": False,
            }
        )
    if report.optional_undocumented:
        fields.append(
            {
                "name": (
                    "Undocumented but has a default "
                    f"({len(report.optional_undocumented)}) — does not fail the build"
                ),
                "value": _usage_field(
                    report, report.optional_undocumented, show_default=True
                ),
                "inline": False,
            }
        )
    history_value = _history_field(report)
    if history_value:
        assert report.history is not None  # guaranteed by _history_field
        fields.append(
            {
                "name": f"Template changed since {report.history.compared_against}",
                "value": history_value,
                "inline": False,
            }
        )
    if report.unused and detect_unused:
        fields.append(
            {
                "name": f"Documented but unused ({len(report.unused)})",
                "value": _truncate(
                    "\n".join(f"• {name}" for name in report.unused), _MAX_FIELD_VALUE
                ),
                "inline": False,
            }
        )
    if fields:
        embed["fields"] = fields

    return {"username": "env-drift-detector", "embeds": [embed]}


def send_to_discord(
    report: DriftReport,
    webhook_url: str,
    *,
    detect_unused: bool = True,
    timeout: float = 10.0,
) -> None:
    """POST the report to Discord.

    Raises:
        DiscordError: on an invalid URL, a network failure, or a non-2xx reply.
            The message never includes the webhook URL.
    """
    url = validate_webhook_url(webhook_url)
    payload = build_payload(report, detect_unused=detect_unused)

    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise DiscordError(f"could not reach Discord: {type(exc).__name__}") from exc

    if response.status_code >= 400:
        raise DiscordError(
            f"Discord rejected the report with HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )
