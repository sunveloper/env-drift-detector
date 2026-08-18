# TODO — remaining work

Every planned stack is now supported. What is left is one known false positive and
two optional refinements. This file records the design so the next session can
pick it up without re-deriving it.

## Current coverage

| Stack | Status | Gap |
| --- | --- | --- |
| Python | Supported | — |
| Node.js | Supported | — |
| Next.js | Supported | Template is usually `.env.local`, so callers must pass `--template .env.local` |
| NestJS | Supported | — |
| Java / Spring Boot | Supported | — |
| docker-compose | Supported | Side effect of sharing `${VAR}` syntax |

## Remaining plan

1. **Wrapped reads** — the two-pass analysis described below. The one known false
   positive. ~2 h
2. **Shape check from the placeholder** — described further down. Optional. ~2 h
3. **Per-stack template auto-detection** — `.env.local` for Next.js, so
   `--template` is not needed. Optional. ~1 h

## Known false positive: reads behind a helper

Found by running the tool on its own repository. `config.py` calls
`_env_flag("ENV_DRIFT_FAIL_ON_MISSING", True)`, and the helper does
`os.getenv(name)` with a variable key. The scanner correctly refuses to guess a
computed key, so the read is never attributed to the literal at the call site,
and `--all` mode reports the variable as unused.

The pattern is common — Django settings modules, NestJS config factories, any
project with a typed settings wrapper — so this matters more than the "no real
codebase does this" cases.

Sketch of a fix: treat a call to a *project-local* function as a read when a
string literal is passed and that function's body reads `os.getenv` from its own
parameter. That is a two-pass analysis — collect wrapper signatures, then resolve
call sites — so it wants its own pass over the module rather than being bolted
onto the current visitor. Estimated ~2 h.

Workaround until then: list the names in `ENV_DRIFT_IGNORE`.

## Done

**Extractor registry.** `extractors/base.py` defines the `Extractor` protocol and
a `Registry` that answers "who handles this file?". `scanner.py` holds no language
knowledge — it decides which files to open and hands each to the registry. More
than one extractor can claim a file, which is how a Nest `.ts` file is scanned for
both `process.env` and `ConfigService`. Adding a stack means adding a module and
appending it to `DEFAULT_EXTRACTORS`.

**NestJS.** `nest.py` covers `configService.get('X')`, the TS generic
`get<string>('X')`, the second-argument default `get('X', 3000)`, a trailing `??`
or `||` fallback, and `getOrThrow` as always-required. Two restrictions keep
`ConfigService`'s non-environment uses out of the report: the receiver name must
contain "config", and the key must be upper snake case.

**Optional usages.** `Usage.optional` and `Usage.default` exist, and
`drift.compare` reports a variable as missing only when at least one read has no
fallback. Reads with a fallback land in `DriftReport.optional_undocumented`, which
reports without failing the build. The Spring extractors inherit this for free:
`${VAR:default}` maps straight onto it.

**Spring Boot.** `property_placeholder.py` reads `${VAR}`, `${VAR:default}`,
`${VAR:-default}` and `${VAR:?error}` from `.yml`, `.yaml`, `.properties`, `.java`
and `.kt` - the last two so `@Value("${DB_URL}")` is covered. `java.py` covers
`System.getenv` and `System.getProperty`, which bypass the property layer. Both
claim `.java`, since a Spring class can use each in one file.

The upper-snake-case rule keeps Spring property keys out: `${DB_URL}` is an
environment variable, `${spring.datasource.url}` resolves against a property
source. The `${VAR}` syntax is shared with docker-compose and shell expansion, so
those files are covered as a side effect, while GitHub Actions' `${{ ... }}` cannot
match because a brace does not start an upper-snake-case name.

Claiming by suffix rather than by the `filenames` field turned out to be the right
call: it picks up profile variants (`application-prod.properties`) with no extra
pattern matching.

**Template revision comparison.** `history.py` compares the working-tree template
against its revision at the base ref, reporting added names, removed names and
changed placeholder values. Git holds the previous revision, so there is no cache.

Caching *real* values was considered and rejected: it would mean storing secrets
at rest, it would require the tool to read production configuration, and a
rotated secret is a normal event that would generate noise. The reasoning is in
the README so it does not get re-litigated.

## Considered: checking real values

Asked directly: if the objection to reading real values is that they are secret,
why not mask them — show the first and last three characters?

Masking is the wrong tool for the storage half of the problem. Detecting "did
this change" needs no value at all, only `HMAC-SHA256(salt, value)`, which is
strictly safer than a mask because a mask stores part of the real secret.

But storage was never the blocker. Reading the value at all is. Hashing or
masking both require the check to run somewhere that holds production
configuration, and today the tool needs access to no environment whatsoever. That
property is worth more than the feature. Masking also leaks the shape of
structured values (`pos...app` gives up the scheme and database name) and fully
recovers low-entropy ones (`tru...rue`).

The signal is weak too: a rotated secret is a normal event, so "changed" cannot
distinguish a correct rotation from a wrong value.

### Done instead: `env-drift verify`

`verify.py` compares each live value against the committed placeholder and
reports two verdicts — `unset` and `still-placeholder` — by name only. It catches
the `.env` copied from `.env.example` and never filled in.

The security boundary is enforced, not just documented: `tests/test_verify.py`
asserts that no value, and no three-character fragment of one, reaches the report
or the rendered output, and that `build_verify_parser` exposes no `webhook`
option. There is deliberately no code path from a real value to an external
service, which is also why `verify` is not part of the push workflow.

A template value that is a genuine default (`PORT=3000`,
`ENV_EXAMPLE_PATH=.env.example`) is not flagged; `--strict-placeholder` opts into
flagging any unchanged value.

### Done: credential-shaped values are redacted

Reviewing the above surfaced a hole in the reporters. Two values in a report come
from the repository - a code fallback literal and a template placeholder - and
both were printed in full. Normally that is fine, but a real key hardcoded as a
default, or pasted into `.env.example`, would have been forwarded straight into
Discord, widening its exposure from "in the repo" to "in a chat channel with
retained history".

`secrets.py` recognises credential shapes (known issuer prefixes, URLs with an
embedded password, opaque high-entropy blobs) and the reporters redact them. The
value is also reported as a `CommittedSecret` finding rather than silently
dropped - the tool is looking straight at a leaked key, so saying so is more use
than staying quiet - and it fails the build.

Self-declared stand-ins stay visible, including AWS's documentation key
`AKIAIOSFODNN7EXAMPLE`, because seeing the placeholder is the point of the report.

### Still open: shape check from the placeholder

`.env.example` says `REDIS_URL=redis://localhost`, so a live value that does not
start with `redis://` or `rediss://` is suspect. Catches a value copied from the
wrong environment, which neither drift detection nor `verify` can see. Would
report "scheme does not match", never the value, and belongs in `verify.py` behind
the same no-values rule. ~2 h

## Open questions

- Should a Spring project compare against `.env.example` at all, or against a
  checked-in `application-example.yml`? Deployments usually inject the values as
  real environment variables, which argues for `.env.example` staying the template.
  Left as is until someone using it in anger says otherwise.
- Next.js splits `.env.local`, `.env.development` and `.env.production`. Worth
  auto-detecting the template per stack instead of requiring `--template`.
- `property-placeholder` claims every `.yml`, which includes CI workflow files. A
  workflow writing `${GITHUB_OUTPUT}` would be reported as an env read. That is
  technically true but not useful; if it becomes noisy, add the common `GITHUB_*`
  names to `DEFAULT_IGNORED` rather than excluding the directory.
