"""Compare what the code reads against what the template documents."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import DriftReport, Usage

DEFAULT_IGNORED = frozenset(
    {
        "PATH",
        "HOME",
        "PWD",
        "TMPDIR",
        "TEMP",
        "USER",
        "USERNAME",
        "LANG",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "VIRTUAL_ENV",
        "NODE_ENV",
        "CI",
        "GITHUB_ACTIONS",
    }
)


def compare(
    usages: Iterable[Usage],
    template_names: Iterable[str],
    *,
    ignored: Iterable[str] | None = None,
    detect_unused: bool = True,
    scanned_files: Sequence[str] = (),
    template_path: str = ".env.example",
    commit: str = "",
    commit_subject: str = "",
    repo: str = "",
) -> DriftReport:
    """Classify each variable as documented, missing, optional-undocumented or unused.

    A variable absent from the template is split by whether the code can cope
    without it:

    * At least one read has no fallback -> ``missing``. The service breaks when
      the value is unset, so this fails the build.
    * Every read has a fallback -> ``optional_undocumented``. Worth adding to the
      template so the knob is discoverable, but nothing breaks without it.

    A variable read both ways counts as ``missing``: the read without a fallback
    is the one that decides whether the service starts.

    Args:
        usages: Every read found by the scanner.
        template_names: Names declared in the env template.
        ignored: Names supplied by the platform, not by the template. Passing a
            value replaces the defaults instead of extending them, so a project
            can opt into strict checking of e.g. ``NODE_ENV``.
        detect_unused: Set False when only part of the tree was scanned. In
            git-diff mode most template entries are legitimately absent from the
            changed files, so reporting them as unused would be pure noise.

    Returns:
        A ``DriftReport`` with every list sorted, for a stable and reviewable diff.
    """
    ignore_set = set(DEFAULT_IGNORED if ignored is None else ignored)
    usage_tuple = tuple(usages)
    template_set = set(template_names)

    required_names: set[str] = set()
    optional_names: set[str] = set()
    for usage in usage_tuple:
        if usage.name in ignore_set:
            continue
        (optional_names if usage.optional else required_names).add(usage.name)

    used_names = required_names | optional_names
    undocumented = used_names - template_set

    missing = sorted(undocumented & required_names)
    optional_undocumented = sorted(undocumented - required_names)
    unused = sorted(template_set - used_names - ignore_set) if detect_unused else []

    return DriftReport(
        missing=tuple(missing),
        unused=tuple(unused),
        optional_undocumented=tuple(optional_undocumented),
        usages=usage_tuple,
        scanned_files=tuple(scanned_files),
        template_path=template_path,
        commit=commit,
        commit_subject=commit_subject,
        repo=repo,
    )
