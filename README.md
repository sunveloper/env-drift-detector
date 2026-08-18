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
| **Missing** | Read with no fallback, and the template does not document it. | Exit code `1`, red Discord embed. |
| **Undocumented but has a default** | Read, undocumented, but every call site supplies a fallback. | Exit code `0`, yellow embed. |
| **Unused** | The template documents it; nothing reads it. | Exit code `0`, yellow embed. Only in `--all` mode. |
| **Ignored** | Platform-supplied names such as `PATH`, `CI`, `NODE_ENV`. | Never reported. |

### Why "has a default" is a separate category

Non-secret settings are usually written with a fallback:

```python
port = os.getenv("PORT", "8000")           # runs fine when unset
level = os.getenv("LOG_LEVEL", "INFO")     # runs fine when unset
key = os.getenv("STRIPE_SECRET_KEY")       # returns None, breaks later
```

Only the third one can break a deployment, so only the third one fails the
build. The first two are still reported — someone cloning the repo should know
the knob exists — but they land in a yellow, non-blocking section. Collapsing
all three into one red alert is what trains a team to ignore the alert.

A variable read both ways counts as **missing**: if any call site cannot cope
without the value, the service can still break.

Detected fallback forms:

| Language | Optional | Required |
| --- | --- | --- |
| Python | `os.getenv("X", "d")`, `os.environ.get("X", "d")`, `environ.setdefault("X", "d")` | `os.getenv("X")`, `os.getenv("X", None)`, `os.environ["X"]` |
| JS / TS | `process.env.X ?? "d"`, `process.env.X \|\| "d"` | `process.env.X` |

`os.environ["X"]` is always required — it raises `KeyError` when unset, so there
is no fallback path. `os.getenv("X", None)` says "no default" as clearly as
omitting the argument, so it is treated as required too.

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

  UNDOCUMENTED but has a default (1) - does not fail the build:
    - BILLING_TIMEOUT_SECONDS (default: "30")  read at src/billing/client.py:19
```

Exit code is `1` because of the two missing entries, so CI stops there. Had
`BILLING_TIMEOUT_SECONDS` been the only finding, the exit code would be `0`.

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
| `0` | Nothing missing, or `--no-fail` was passed. Undocumented-with-a-default and stale template entries report but do not fail. |
| `1` | Variables are read without a fallback and are not documented. |
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

## Where the real values live

**No `.env` file is deployed anywhere.** In CI this tool needs exactly one real
value — the Discord webhook URL — and it reads it from the environment, which is
what a CI secret store injects.

| Item | Location | Committed? |
| --- | --- | --- |
| `.env.example` | In the repository | Yes — placeholders only |
| `.env` | Developer machines only | No — listed in `.gitignore` |
| The real `DISCORD_WEBHOOK_URL` | CI secret store | Not a file at all |

`load_dotenv()` in `cli.py` is a local convenience. When `.env` is absent it
does nothing and the process environment is used instead, which is exactly the
CI path — so no workflow step has to create a file.

Why not just write a `.env` during the CI run:

- The content would have to come from somewhere. Committing it puts a
  credential in git history permanently, and history is hard to purge.
- GitHub masks secret values in workflow logs automatically. A file that a build
  step `cat`s is not masked by anything.

### Other CI platforms

The tool only ever reads environment variables, so nothing in the code changes:

| Platform | Where to put the webhook URL |
| --- | --- |
| GitHub Actions | Settings → Secrets and variables → Actions |
| GitLab CI | Settings → CI/CD → Variables, tick **Masked** |
| Jenkins | Credentials → Secret text, then `withCredentials` |
| Azure DevOps | Pipeline → Variables, tick **Keep this value secret** |

### Scanning a different repository

The `.env.example` being checked belongs to the repository under scan, not to
this tool. That file is already committed there as a matter of course, and the
tool reads it straight from the working tree — there is nothing extra to
prepare.

That repository's *real* values are never needed either. The comparison is
between variable **names**, so the tool never reads a value. This is why it can
run in CI without any access to production secrets.

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
| `scanner.py` | Env var reads found in source, with `file:line` and whether the read has a fallback. |
| `template.py` | Names declared in the env template. |
| `drift.py` | Classify: missing / undocumented-with-default / unused / ignored. |
| `models.py` | `Usage` and `DriftReport` — the values passed between stages. |
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
- A fallback is only recognised at the read itself. `value = os.getenv("X") or
  "default"` on the next line, or a default applied inside a config class, still
  reports as required. Again, over-reporting rather than staying silent.
- Reads wrapped in a helper are invisible. If a project calls
  `env_flag("FEATURE_X", True)` and the helper does `os.getenv(name)` internally,
  the scanner sees a computed key and skips it — so `FEATURE_X` shows up as
  *unused* in `--all` mode even though it is read. This tool's own `config.py`
  has that shape, which is how the limitation was found. Workaround for now: add
  such names to `ENV_DRIFT_IGNORE`. Tracked in `TODO.md`.
- The tool cannot tell a secret from a plain setting — it never reads values, so
  it has nothing to judge that on. Both must appear in the template, which is
  the point: the template answers "what do I need to set", not "what is secret".
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
