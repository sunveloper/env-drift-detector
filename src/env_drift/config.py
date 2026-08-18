"""Resolve settings from CLI flags, then the environment, then defaults.

Keeping resolution in one place means the CLI never reads ``os.environ``
directly, so precedence is testable and documented in exactly one spot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .drift import DEFAULT_IGNORED


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_names(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


@dataclass(frozen=True)
class Config:
    repo_path: Path
    template_path: Path
    webhook_url: str | None
    ignored: set[str]
    fail_on_missing: bool
    scan_all: bool
    base_ref: str | None
    head_ref: str
    dry_run: bool
    notify_on_success: bool

    @classmethod
    def resolve(
        cls,
        *,
        repo: str | None,
        template: str | None,
        webhook: str | None,
        ignore: str | None,
        scan_all: bool,
        base: str | None,
        head: str,
        dry_run: bool,
        notify_on_success: bool,
        fail_on_missing: bool | None,
    ) -> Config:
        repo_path = Path(repo or ".").resolve()
        template_name = template or os.getenv("ENV_EXAMPLE_PATH") or ".env.example"
        template_path = Path(template_name)
        if not template_path.is_absolute():
            template_path = repo_path / template_path

        ignored = _split_names(ignore) or _split_names(os.getenv("ENV_DRIFT_IGNORE"))

        return cls(
            repo_path=repo_path,
            template_path=template_path,
            # A CLI-provided webhook wins, but the environment is the intended
            # channel - a URL on the command line lands in shell history.
            webhook_url=webhook or os.getenv("DISCORD_WEBHOOK_URL"),
            ignored=ignored if ignored is not None else set(DEFAULT_IGNORED),
            fail_on_missing=(
                fail_on_missing
                if fail_on_missing is not None
                else _env_flag("ENV_DRIFT_FAIL_ON_MISSING", True)
            ),
            scan_all=scan_all,
            base_ref=base or os.getenv("ENV_DRIFT_BASE_REF") or None,
            head_ref=head,
            dry_run=dry_run,
            notify_on_success=notify_on_success,
        )
