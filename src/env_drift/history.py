"""Compare the env template against its previous revision in git.

The question this answers: "the template changed in this push - what does the
team have to do about it?" A removed variable means someone's local `.env` now
has a stale entry; a changed placeholder usually means the *format* changed
(``redis://`` becoming ``rediss://``) and everyone has to update their own value.

Why there is no cache here. Only the template is compared, and the template holds
placeholders and is already committed - git is the store, so nothing needs
persisting. Real values are deliberately never read: storing secrets at rest
would need encryption and key management, and it would mean the tool needs access
to production configuration, which is exactly the dependency it avoids having.
Rotating a secret is also normal and healthy, so alerting on a changed real value
would be pure noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .git_source import file_at_ref
from .template import parse_template_entries


@dataclass(frozen=True)
class PlaceholderChange:
    """One variable whose placeholder value differs from the previous revision."""

    name: str
    before: str
    after: str


@dataclass(frozen=True)
class TemplateHistory:
    """What changed in the template between two revisions."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    placeholder_changed: tuple[PlaceholderChange, ...] = ()
    compared_against: str = ""
    """The ref the current template was compared with. Empty when no comparison ran."""

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.placeholder_changed)

    @property
    def needs_local_action(self) -> bool:
        """True when developers must edit their own `.env` to stay working.

        An added variable needs a value; a changed placeholder usually signals a
        changed format. A removed one is only tidy-up, so it does not qualify.
        """
        return bool(self.added or self.placeholder_changed)


def compare_template_revisions(current: str, previous: str, ref: str = "") -> TemplateHistory:
    """Diff two template texts by name and by placeholder value."""
    now = parse_template_entries(current)
    before = parse_template_entries(previous)

    changed = tuple(
        PlaceholderChange(name=name, before=before[name], after=now[name])
        for name in sorted(set(now) & set(before))
        if now[name] != before[name]
    )
    return TemplateHistory(
        added=tuple(sorted(set(now) - set(before))),
        removed=tuple(sorted(set(before) - set(now))),
        placeholder_changed=changed,
        compared_against=ref,
    )


def template_history(
    root: Path, template_path: Path, base_ref: str
) -> TemplateHistory:
    """Compare the working-tree template against its revision at ``base_ref``.

    Returns an empty history - not an error - when the template did not exist at
    that ref, or when it is untracked. There is simply nothing to compare, which
    is the normal case for the commit that introduces the template.
    """
    try:
        relative = template_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # A template outside the repository has no history in it.
        return TemplateHistory()

    previous = file_at_ref(root, base_ref, relative)
    if previous is None:
        return TemplateHistory()

    current = template_path.read_text(encoding="utf-8", errors="replace")
    return compare_template_revisions(current, previous, ref=base_ref)
