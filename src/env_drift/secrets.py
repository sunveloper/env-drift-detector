"""Recognise a value that looks like a credential, so it is never re-published.

Two values in a report come from the repository itself: a fallback literal in the
source (``os.getenv("PORT", "8000")``) and a placeholder in the env template.
Printing them is normally fine - anyone who can read the repo can read them.

The exception is a value that should never have been committed. A hardcoded
``sk_live_…`` default, or a real key pasted into ``.env.example``, is already a
serious bug; echoing it into a Discord channel makes it worse, because chat
history is retained and usually readable by more people than the repository is.

So a credential-shaped value is redacted in the output *and* reported as a
finding. Staying silent about it would waste the one moment the tool is looking
straight at it.

This is a shape heuristic, not a decision about secrecy. It errs toward
redacting: a redacted non-secret costs a reader one `git show`, while the reverse
mistake cannot be undone.
"""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit

REDACTED = "[redacted - looks like a credential]"

# Prefixes and formats published by the issuers themselves. Matched case-sensitively
# where the issuer specifies case.
_CREDENTIAL_PATTERNS = (
    re.compile(r"^sk_(live|test)_[A-Za-z0-9]{8,}"),        # Stripe secret key
    re.compile(r"^rk_(live|test)_[A-Za-z0-9]{8,}"),        # Stripe restricted key
    re.compile(r"^gh[pousr]_[A-Za-z0-9]{16,}"),            # GitHub token
    re.compile(r"^github_pat_[A-Za-z0-9_]{20,}"),          # GitHub fine-grained PAT
    re.compile(r"^xox[baprs]-[A-Za-z0-9-]{10,}"),          # Slack token
    re.compile(r"^AKIA[0-9A-Z]{16}$"),                     # AWS access key id
    re.compile(r"^ASIA[0-9A-Z]{16}$"),                     # AWS temporary key id
    re.compile(r"^AIza[0-9A-Za-z_\-]{30,}"),               # Google API key
    re.compile(r"^ya29\.[0-9A-Za-z_\-]{20,}"),             # Google OAuth token
    re.compile(r"^SG\.[A-Za-z0-9_\-]{16,}"),               # SendGrid
    re.compile(r"^dop_v1_[a-f0-9]{32,}"),                  # DigitalOcean
    re.compile(r"^glpat-[A-Za-z0-9_\-]{16,}"),             # GitLab PAT
    re.compile(r"^npm_[A-Za-z0-9]{30,}"),                  # npm token
    re.compile(r"^-----BEGIN [A-Z ]*PRIVATE KEY-----"),    # PEM private key
    re.compile(r"^eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."),  # JWT
)

# A long, high-entropy blob with no structure a human would write.
_OPAQUE = re.compile(r"^[A-Za-z0-9+/=_\-]{32,}$")
_ENTROPY_THRESHOLD = 3.6

# Words that mean "this is a stand-in", which outrank the shape heuristics: a
# placeholder is allowed to be long and random-looking.
_STANDIN_MARKERS = (
    "replace",
    "changeme",
    "change-me",
    "change_me",
    "example",
    "placeholder",
    "your",
    "dummy",
    "fixme",
    "todo",
    "sample",
    "redacted",
)


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character. Around 4.0 for random base64, under 3 for prose."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _url_has_embedded_credential(value: str) -> bool:
    """``postgres://user:password@host/db`` - the password is in the value."""
    if "://" not in value:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if not parts.password:
        return False
    # A template commonly writes redis://user:pass@host as an illustration.
    return not _is_stand_in(parts.password)


def _is_stand_in(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _STANDIN_MARKERS)


def looks_like_secret(value: str | None) -> bool:
    """Whether a committed value has the shape of a real credential.

    False for anything short, structured, or self-declared as a placeholder.
    """
    if not value:
        return False
    candidate = value.strip()
    if not candidate:
        return False

    # An explicit stand-in is never treated as a secret, however random it looks.
    # Checked before the patterns so that a documented example such as
    # "sk_test_replace_me" stays visible - seeing it is the point of the report.
    if _is_stand_in(candidate):
        return False

    if any(pattern.match(candidate) for pattern in _CREDENTIAL_PATTERNS):
        return True

    if _url_has_embedded_credential(candidate):
        return True

    if _OPAQUE.match(candidate) and shannon_entropy(candidate) >= _ENTROPY_THRESHOLD:
        return True

    return False


def safe(value: str | None) -> str | None:
    """A value fit for a report: the value itself, or the redaction marker."""
    if value is None:
        return None
    return REDACTED if looks_like_secret(value) else value
