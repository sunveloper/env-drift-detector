# env-drift-detector

Catches the deploy that would have failed because `.env.example` was never updated.

When a push adds `os.getenv("STRIPE_WEBHOOK_SECRET")` but nobody adds
`STRIPE_WEBHOOK_SECRET` to `.env.example`, nothing breaks in the author's
environment — the value is already in their local `.env`. It breaks for the next
person who clones the repo, and it breaks on staging, usually as a `None` that
surfaces three layers away from the real cause.

This tool scans the files touched by the latest push, finds every environment
variable the code reads, compares that against the env template, and posts the
result to a Discord channel.

## Who it is for

**Backend developers** who own service configuration, and by extension anyone
who has to run the service: a new joiner setting up locally, a tester bringing
up a fresh environment, whoever is on deploy duty.

## What it reports

| Category | Meaning | Effect |
| --- | --- | --- |
| **Missing** | The code reads it; the template does not document it. | Exit code `1`, red Discord embed. |
| **Unused** | The template documents it; nothing reads it. | Exit code `0`, yellow embed. Only in `--all` mode. |
| **Ignored** | Platform-supplied names such as `PATH`, `CI`, `NODE_ENV`. | Never reported. |

"Unused" is deliberately suppressed in the default push mode. Scanning only the
changed files means most template entries are legitimately absent from the scan
set, so reporting them would be noise. Run `--all` when you want that answer.

## Languages scanned

| Language | Detected via | Patterns |
| --- | --- | --- |
| Python (`.py`, `.pyi`) | `ast` parse | `os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")`, `environ.setdefault("X", ...)` |
| JS / TS (`.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`) | regex | `process.env.X`, `process.env["X"]`, `import.meta.env.X` |

Python uses a real parser, so a variable name inside a comment or a docstring is
not a false positive. Computed keys (`os.getenv(prefix + "NAME")`) are skipped —
their value is not knowable without running the code.

## Setup

Prerequisites: Python 3.10 or newer, and `git` on `PATH`.

```bash
git clone <your-fork-url> env-drift-detector
cd env-drift-detector
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Configure:

```bash
cp .env.example .env
# then edit .env and paste your Discord webhook URL
```

Get a webhook URL from Discord: **Server Settings → Integrations → Webhooks →
New Webhook → Copy Webhook URL**. Treat it as a credential — anyone holding it
can post to that channel.

## Usage

Check the current repository's latest commit:

```bash
env-drift
```

Check without sending anything to Discord:

```bash
env-drift --dry-run
```

Sample output when drift is found:

```
env-drift: scanned 3 file(s) against .env.example
  commit 9f2c41ab  feat(billing): add Stripe webhook handler

  MISSING from .env.example (2):
    - STRIPE_WEBHOOK_SECRET  read at src/billing/webhook.py:24
    - STRIPE_API_VERSION  read at src/billing/client.py:11, src/billing/client.py:58
```

Exit code is `1`, so CI stops there.

### Common invocations

```bash
env-drift                                  # latest commit, notify Discord
env-drift --dry-run                        # latest commit, terminal only
env-drift --all                            # whole tree, includes unused detection
env-drift --base origin/main               # everything since main (a whole PR)
env-drift --repo ../other-service          # a different repository
env-drift --ignore SENTRY_DSN,DEBUG_PORT   # skip specific names
env-drift --no-fail                        # report but always exit 0
env-drift --notify-on-success              # also post the green "all clear"
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No missing variables, or `--no-fail` was passed. |
| `1` | Variables are read but not documented. |
| `2` | The tool could not run: not a git repo, template missing, webhook failed. |

## Run it on every push

`.github/workflows/env-drift.yml` is included and ready. Two steps to enable it:

1. Add a repository secret named `DISCORD_WEBHOOK_URL`
   (**Settings → Secrets and variables → Actions → New repository secret**).
2. Push. The workflow uses `github.event.before` as the diff base, so a push of
   five commits is checked as one range, not just the tip.

Prefer to catch it before it leaves your machine? Install the local hook:

```bash
cp hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

## Configuration

Flags win over environment variables, which win over defaults.

| Variable | Flag | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_WEBHOOK_URL` | `--webhook` | none | Where reports go. Without it, output stays in the terminal. |
| `ENV_EXAMPLE_PATH` | `--template` | `.env.example` | Template to compare against. |
| `ENV_DRIFT_IGNORE` | `--ignore` | see table above | Comma-separated names to skip. Replaces the default list rather than extending it. |
| `ENV_DRIFT_FAIL_ON_MISSING` | `--no-fail` | `true` | Whether missing variables fail the run. |
| `ENV_DRIFT_BASE_REF` | `--base` | `HEAD^` | Start of the range to diff. |

Passing `--webhook` on the command line puts a credential in your shell history.
Use the environment variable instead.

## Tech stack

- **Python 3.10+** — `ast` from the standard library does the Python parsing.
- **httpx** — Discord webhook delivery.
- **python-dotenv** — loads `.env` for local runs.
- **git** — shelled out to for the changed-file list and commit metadata.
- **pytest** — test suite.
- **GitHub Actions** — the push trigger.

## How it works

```
git diff (changed files) -> scanner (ast / regex) -> compare vs template -> console + Discord
```

Each stage is a separate module with no knowledge of the next, which is why the
scanner can be tested on plain strings and the comparison on plain sets:

| Module | Responsibility |
| --- | --- |
| `git_source.py` | Which files the push touched; commit metadata. |
| `scanner.py` | Env var reads found in source, with `file:line`. |
| `template.py` | Names declared in the env template. |
| `drift.py` | Classify: missing / unused / ignored. |
| `reporters/` | Render to terminal or Discord. |
| `config.py` | Flag, then environment, then default precedence. |
| `cli.py` | Wire the stages together; own the exit codes. |

## Tests

```bash
pytest -q
```

The integration tests build throwaway git repositories on the fly and run the
real CLI against them, including the cases that are easy to get wrong: a repo
whose first commit has no parent, a push that must *not* report pre-existing
drift in files it did not touch, and a multi-commit push with an explicit base.

## Assumptions and limits

- Variable names must be string literals. Dynamically built names are skipped
  rather than guessed.
- `.env.example` is the source of truth for what a variable is *called*, not for
  what its value should be. Values in it are placeholders.
- JS/TS detection is regex-based, so `process.env` inside a JS comment counts as
  a usage. That errs toward over-reporting, which is the safer direction.
- Only the template is compared. The tool does not read the values present in a
  live environment, so it cannot tell you that staging is missing a value it
  does document. That is deliberate: it needs no production access to run.

## Security

- The webhook URL is read from the environment, never printed, and never
  included in an error message.
- The destination host is validated against Discord's own domains, so a tampered
  environment variable cannot redirect reports to an attacker's endpoint.
- Reports contain variable *names* and `file:line` locations. Never values.
- `.env` is in `.gitignore`; `.env.example` holds placeholders only.
