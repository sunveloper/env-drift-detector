"""Resolve which files a push touched, using git as the source of truth.

The CLI needs three things from git: the changed files for the pushed range,
the commit metadata for the report, and the repository root so paths in the
report are repo-relative. Everything here shells out to ``git`` rather than
depending on a library, so the tool works anywhere git itself does.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command fails or the directory is not a repository."""


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str
    author: str


def _run(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # git not installed
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}") from exc
    return result.stdout.strip()


def repo_root(start: Path) -> Path:
    """The top level of the repository containing ``start``."""
    return Path(_run(["rev-parse", "--show-toplevel"], start))


def commit_info(root: Path, ref: str = "HEAD") -> CommitInfo:
    raw = _run(["log", "-1", "--format=%H%x1f%s%x1f%an", ref], root)
    sha, _, rest = raw.partition("\x1f")
    subject, _, author = rest.partition("\x1f")
    return CommitInfo(sha=sha, subject=subject, author=author)


def changed_files(root: Path, base: str | None = None, head: str = "HEAD") -> list[Path]:
    """Files added, copied, modified or renamed between ``base`` and ``head``.

    Deleted files are excluded (``--diff-filter=ACMR``) because there is nothing
    left to scan in them, and a deletion that removes the last read of a
    variable already surfaces as "unused" via the full template comparison.

    When ``base`` is omitted the parent of ``head`` is used. For a repository's
    very first commit there is no parent, so the commit's own tree is listed
    instead.
    """
    if base is None:
        if _has_parent(root, head):
            base = f"{head}^"
        else:
            names = _run(["show", "--name-only", "--format=", head], root)
            return _to_paths(root, names)

    names = _run(["diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"], root)
    return _to_paths(root, names)


def _has_parent(root: Path, ref: str) -> bool:
    try:
        _run(["rev-parse", "--verify", "--quiet", f"{ref}^"], root)
    except GitError:
        return False
    return True


def _to_paths(root: Path, output: str) -> list[Path]:
    return [root / name for name in output.splitlines() if name.strip()]
