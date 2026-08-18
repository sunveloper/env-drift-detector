"""Output adapters. Each takes a DriftReport and renders it somewhere."""

from .console import render_console
from .discord import DiscordError, build_payload, send_to_discord

__all__ = ["render_console", "build_payload", "send_to_discord", "DiscordError"]
