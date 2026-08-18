"""Command-line entry point: scan the pushed commit, report drift, notify Discord.

Exit codes:
    0  no missing variables (or ``--no-fail`` was given)
    1  variables are read by the code but absent from the template
    2  the tool could not run (bad repo, missing template, webhook failure)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import Config
from .drift import compare
from .git_source import GitError, changed_files, commit_info, repo_root
from .reporters import DiscordError, render_console, send_to_discord
from .scanner import iter_source_files, scan_paths

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="env-drift",
        description=(
            "Scan the files touched by the latest push for environment variable "
            "reads, compare them against .env.example, and report drift to Discord."
        ),
    )
    parser.add_argument("--repo", help="Path to the repository (default: current directory)")
    parser.add_argument("--template", help="Env template to compare against (default: .env.example)")
    parser.add_argument(
        "--webhook",
        help="Discord webhook URL. Prefer the DISCORD_WEBHOOK_URL environment variable - "
        "a URL passed here is recorded in shell history.",
    )
    parser.add_argument("--ignore", help="Comma-separated variable names to skip")
    parser.add_argument(
        "--all",
        dest="scan_all",
        action="store_true",
        help="Scan the whole tree instead of only the pushed changes. "
        "Required to detect variables that are documented but no longer used.",
    )
    parser.add_argument("--base", help="Base ref of the pushed range (default: HEAD^)")
    parser.add_argument("--head", default="HEAD", help="Head ref to scan (default: HEAD)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report without sending anything to Discord",
    )
    parser.add_argument(
        "--notify-on-success",
        action="store_true",
        help="Also send a Discord message when no drift is found",
    )
    parser.add_argument(
        "--no-fail",
        dest="fail_on_missing",
        action="store_const",
        const=False,
        default=None,
        help="Always exit 0, even when variables are missing",
    )
    parser.add_argument("--version", action="version", version=f"env-drift {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # local convenience; in CI the values come from the environment
    args = build_parser().parse_args(argv)

    config = Config.resolve(
        repo=args.repo,
        template=args.template,
        webhook=args.webhook,
        ignore=args.ignore,
        scan_all=args.scan_all,
        base=args.base,
        head=args.head,
        dry_run=args.dry_run,
        notify_on_success=args.notify_on_success,
        fail_on_missing=args.fail_on_missing,
    )

    try:
        report = run(config)
    except GitError as exc:
        print(f"env-drift: git error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"env-drift: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(render_console(report, detect_unused=config.scan_all))

    should_notify = config.webhook_url and not config.dry_run and (
        report.has_drift or config.notify_on_success
    )
    if should_notify:
        try:
            send_to_discord(report, config.webhook_url, detect_unused=config.scan_all)
        except DiscordError as exc:
            print(f"env-drift: could not notify Discord: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print("env-drift: report sent to Discord.")
    elif report.has_drift and not config.webhook_url:
        print("env-drift: DISCORD_WEBHOOK_URL not set - report not sent.", file=sys.stderr)

    if report.missing and config.fail_on_missing:
        return EXIT_DRIFT
    return EXIT_OK


def run(config: Config):
    """Do the work and return a DriftReport. Raises GitError / FileNotFoundError."""
    from .template import parse_template

    root = repo_root(config.repo_path)

    if not config.template_path.is_file():
        raise FileNotFoundError(
            f"env template not found: {config.template_path}. "
            "Create it, or point at another file with --template."
        )
    template_names = parse_template(config.template_path)

    if config.scan_all:
        files: list[Path] = iter_source_files(root)
        commit = commit_info(root, config.head_ref)
    else:
        files = changed_files(root, base=config.base_ref, head=config.head_ref)
        commit = commit_info(root, config.head_ref)

    usages = scan_paths(files, root)
    scanned = tuple(
        path.resolve().relative_to(root.resolve()).as_posix()
        for path in files
        if path.is_file() and _is_within(path, root)
    )

    return compare(
        usages,
        template_names,
        ignored=config.ignored,
        detect_unused=config.scan_all,
        scanned_files=scanned,
        template_path=config.template_path.name,
        commit=commit.sha,
        commit_subject=commit.subject,
        repo=root.name,
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
