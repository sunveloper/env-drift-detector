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
| **Committed credential** | A value in the repo has the shape of a real key. | Exit code `1`, red embed. Value redacted. |
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

### Committed credentials

Two values in a report come from the repository itself: a fallback literal in the
source, and a placeholder in the template.

```python
os.getenv("PORT", "8000")          # the report prints: PORT (default `8000`)
```

Printing those is normally fine — anyone who can read the repo can read them. The
exception is a value that should never have been committed:

```python
os.getenv("API_KEY", "sk_live_51H8sQ…")   # hardcoded in the source
```
```bash
# .env.example
STRIPE_SECRET_KEY=sk_live_51H8sQ…         # a real key pasted into the template
```

Both are already serious bugs, and echoing the value into a Discord channel makes
them worse: chat history is retained and usually readable by more people than the
repository is. So a credential-shaped value is **redacted in the output and
reported as a finding**:

```
  COMMITTED CREDENTIAL (1) - rotate the value, then remove it from the repository:
    ! API_KEY  code default at src/billing/client.py:12
```

The report carries the variable name, the origin and the kind — never the value,
not even a fragment of it. `tests/test_secrets.py` asserts that no 8-, 12- or
16-character slice of a credential reaches the output.

This fails the build. A committed credential should stop a pipeline, and
`--no-fail` is the escape hatch if the detection misfires.

#### What counts as credential-shaped

- **Known issuer formats** — `sk_live_`, `sk_test_`, `ghp_`, `github_pat_`,
  `xoxb-`, `AKIA…`, `AIza…`, `SG.`, `glpat-`, `npm_`, `dop_v1_`, a PEM private key
  header, a JWT.
- **URLs with an embedded password** — `postgres://user:realpassword@host/db`.
- **Opaque high-entropy blobs** — 32+ characters of base64/hex with Shannon
  entropy at or above 3.6 bits per character.

A value that declares itself a stand-in is never redacted, however random it
looks, because seeing the placeholder is the point of the report. That covers
`sk_live_replace_with_your_key`, `postgres://admin:changeme@localhost/db`, and
AWS's own documentation key `AKIAIOSFODNN7EXAMPLE`.

This is a shape heuristic, not a judgement about secrecy. It errs toward
redacting: a redacted non-secret costs the reader one `git show`, while the
opposite mistake cannot be undone.

## Template changes

Drift detection answers "is the template complete?". A second question matters
just as much: "the template changed — what do I have to do about it?" Git already
stores the previous revision of `.env.example`, so the tool reads it with
`git show <base>:.env.example` and reports the difference:

| Change | Reported as | Asks for local action? |
| --- | --- | --- |
| Variable added | `+ NAME (add it to your .env)` | Yes |
| Placeholder value changed | `~ NAME  "redis://…" -> "rediss://…"` | Yes — the format changed |
| Variable removed | `- NAME (safe to drop from your .env)` | No |

A placeholder change is the useful one in practice. When `REDIS_URL` goes from
`redis://` to `rediss://`, nothing is missing and no test fails — but every
developer's local value is now wrong, and they find out one at a time. This turns
that into one Discord message.

Only added variables and changed placeholders colour the Discord embed yellow; a
removal is tidy-up, not a task. None of them affect the exit code. Turn the whole
comparison off with `--no-template-history` or
`ENV_DRIFT_TEMPLATE_HISTORY=false`.

Quoting is normalised before comparison, so changing `A=x` to `A="x"` is not
reported. Comment-only edits are not reported either.

### Why real values are never read

The obvious extension is to compare the *real* values and alert when one changes.
This tool deliberately does not. The reason is not the storage — that part is
solvable — it is the access.

**Storage is solvable, and masking is the wrong solution for it.** Detecting "did
this change" needs no value at all, only `HMAC-SHA256(salt, value)`. That is
strictly safer than showing the first and last three characters, because a mask
stores part of the actual secret. So if storage were the only problem, hashing
would settle it.

**Access is not solvable.** Hashing or masking still requires reading the real
value first, which means injecting production configuration into the job that
runs the check. Today this tool needs no access to any environment — that is what
makes it safe to run on every push, and what a masking feature would quietly give
up. A CI job holding every secret for every environment is a much bigger problem
than an undocumented variable.

**And masking leaks more than it appears to.** Structured values give up their
shape in the first and last few characters:

```
postgres://admin:S3cr3t@db.internal:5432/app   ->  pos...app   (scheme, database name)
sk_test_a1b2c3                                 ->  sk_...2c3   (test key, not live)
DEBUG=true                                     ->  tru...rue   (fully recovered)
```

Six characters of a twenty-character token is 30% of it, and Discord history is
retained and usually readable by more people than the secret store is.

**Finally, "changed" is a weak signal.** Rotating a secret is normal and healthy,
so an alert on every change is noise. It does not distinguish a correct rotation
from a wrong value.

The useful version of this request is implemented instead, as
[`env-drift verify`](#env-drift-verify): it compares a live value against the
committed *placeholder*, answering "is this value wrong" rather than "did it
change", and it runs where the value already legitimately lives.

The template is a different case entirely: its values are placeholders by
definition, and it is already committed to the repository. Comparing it needs no
cache and no access — git is the store.

## `env-drift verify`

The main command asks "is the template complete?". This asks the other half: "the
template is complete — is *my* environment?" It catches the `.env` that was copied
from `.env.example` and never edited, which is the most common way a correctly
documented variable still ends up wrong.

```bash
env-drift verify                      # check the process environment
env-drift verify --env-file .env      # check a specific file instead
env-drift verify --strict-placeholder # flag any value still equal to the template
env-drift verify --no-fail            # report without failing
```

```
env-drift verify: checked 6 variable(s) from .env.example against the process environment

  NOT SET (2):
    - DATABASE_URL
    - REDIS_URL

  STILL THE TEMPLATE PLACEHOLDER (1):
    - STRIPE_SECRET_KEY
```

Exit code `1` when there are findings, `2` if the template or `--env-file` is
missing.

### What counts as a finding

| Situation | Reported |
| --- | --- |
| Template value is non-empty, live value is missing or blank | `NOT SET` |
| Live value equals the template value, and that value looks like a stand-in | `STILL THE TEMPLATE PLACEHOLDER` |
| Live value equals the template value, and that value is a genuine default | Not reported |
| Template value is empty | Not reported — the template says no value is needed |

A template may hold real defaults: `PORT=3000`, `LOG_LEVEL=INFO`,
`ENV_EXAMPLE_PATH=.env.example`. An environment that keeps those is correct, so
flagging them would make the command useless in exactly the projects that write
good templates. A stand-in is recognised by markers such as `replace`, `changeme`,
`your-`, `placeholder`, `<...>`, `@example.com`, or a run of six or more identical
characters. Use `--strict-placeholder` for a project whose template holds no real
defaults.

### Where to run it

This command reads real values, so run it somewhere they already belong: a
developer's machine, or a deploy job that already has the configuration injected.
Two properties make that safe:

- **A report holds variable names and a verdict. No value, no hash, no prefix, no
  length.** `tests/test_verify.py` asserts this, including that no three-character
  fragment of a value appears in the output.
- **Nothing is persisted and nothing is sent anywhere.** `verify` has no
  `--webhook` option — deliberately, so there is no code path from a real value to
  an external service. A test asserts that option does not exist.

This is also why `verify` is not part of the push workflow: CI has no business
holding production configuration for a lint check.

## Languages scanned

| Extractor | Files | Detected via | Patterns |
| --- | --- | --- | --- |
| `python` | `.py`, `.pyi` | `ast` parse | `os.getenv("X")`, `os.environ["X"]`, `os.environ.get("X")`, `environ.setdefault("X", ...)` |
| `javascript` | `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs` | regex | `process.env.X`, `process.env["X"]`, `import.meta.env.X` |
| `nest-config` | same as `javascript` | regex | `configService.get('X')`, `get<string>('X')`, `get('X', default)`, `getOrThrow('X')` |

By stack:

| Stack | Covered by |
| --- | --- |
| Python | `python` |
| Node.js, Express | `javascript` |
| Next.js | `javascript` — pass `--template .env.local` if that is the project's template |
| NestJS | `javascript` + `nest-config`, both run over the same file |
| Java / Spring Boot | Not yet — see `TODO.md` |

Python uses a real parser, so a variable name inside a comment or a docstring is
not a false positive. Computed keys (`os.getenv(prefix + "NAME")`) are skipped —
their value is not knowable without running the code.

`ConfigService` also serves configuration that has nothing to do with the
environment, so `nest-config` applies two restrictions. The receiver name must
contain "config" (`configService`, `config`, `appConfig`) — `userService.get('X')`
is a data lookup. And the key must be upper snake case, because Nest's namespaced
keys (`config.get('app.port')`) resolve against a config object rather than the
environment. `getOrThrow` is always treated as required: it states outright that
an unset value is fatal.

### Adding a stack

Each extractor is one module under `src/env_drift/extractors/`, exposing a class
that satisfies the `Extractor` protocol in `extractors/base.py`:

```python
class Extractor(Protocol):
    name: str
    suffixes: frozenset[str]   # claimed file suffixes
    filenames: frozenset[str]  # claimed exact file names, e.g. application.yml

    def extract(self, source: str, relative_path: str) -> list[Usage]: ...
```

Register the instance in `extractors/__init__.py` and it is live. The scanner, the
comparison and the reporters need no changes — they only ever see `list[Usage]`.
More than one extractor may claim the same file, which is how a Nest `.ts` file
gets scanned for both `process.env` and `ConfigService` without either extractor
knowing about the other.

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

  TEMPLATE CHANGED since HEAD^:
    ~ REDIS_URL  placeholder changed: "redis://localhost" -> "rediss://localhost"
    Everyone should refresh their local .env.
```

Exit code is `1` because of the two missing entries, so CI stops there. Had
`BILLING_TIMEOUT_SECONDS` been the only finding, the exit code would be `0`.

There is a second command, `env-drift verify`, documented
[below](#env-drift-verify).

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
env-drift --no-template-history            # skip the template-revision comparison
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Nothing missing, or `--no-fail` was passed. Undocumented-with-a-default and stale template entries report but do not fail. |
| `1` | Variables are read without a fallback and are not documented, or a committed credential was found. |
| `2` | The tool could not run: not a git repo, template missing, webhook failed. |

Both commands use the same codes.

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
| `ENV_DRIFT_TEMPLATE_HISTORY` | `--no-template-history` | `true` | Whether to compare the template against its previous revision. |

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
git diff (changed files) -> registry picks extractors -> compare vs template -> console + Discord
```

Each stage is a separate module with no knowledge of the next, which is why the
scanner can be tested on plain strings and the comparison on plain sets:

| Module | Responsibility |
| --- | --- |
| `git_source.py` | Which files the push touched; commit metadata. |
| `scanner.py` | Which files to open; hands each to the registry. No language knowledge. |
| `extractors/` | One module per stack. Env var reads with `file:line` and whether the read has a fallback. |
| `template.py` | Names and placeholder values declared in the env template. |
| `verify.py` | `env-drift verify` — classifies a live environment. Emits names only. |
| `secrets.py` | Recognises a credential-shaped value so it is never re-published. |
| `history.py` | How the template changed since the base revision. |
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
- JS/TS and Nest detection are regex-based, so `process.env` inside a JS comment
  counts as a usage. That errs toward over-reporting, which is the safer direction.
- A Nest config key in lower case or with a dot is treated as non-environment and
  skipped. A project that genuinely reads `config.get('port')` from the
  environment will not be covered.
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
- Reports contain variable *names* and `file:line` locations. Values appear only
  when they are already committed to the repository, and never when they look like
  a credential — see [Committed credentials](#committed-credentials).
- `env-drift verify` reads real values and emits none of them, not even a
  fragment. Both properties are asserted by tests.
- `.env` is in `.gitignore`; `.env.example` holds placeholders only.
