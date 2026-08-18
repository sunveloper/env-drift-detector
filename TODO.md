# TODO — remaining work

Java / Spring Boot support and one known false positive. This file records the
design so the next session can pick it up without re-deriving it.

## Current coverage

| Stack | Status | Gap |
| --- | --- | --- |
| Python | Supported | — |
| Node.js | Supported | — |
| Next.js | Supported | Template is usually `.env.local`, so callers must pass `--template .env.local` |
| NestJS | Supported | — |
| Java / Spring Boot | Not supported | `.java`, `application.yml` and `application.properties` are never scanned |

## Remaining plan

1. **Spring Boot extractors** — `spring_props.py` for `${VAR}` / `${VAR:default}`
   in `application.yml` and `application.properties`, plus `java.py` for
   `System.getenv` and `System.getProperty`. The protocol's `filenames` field
   already exists for the `application.*` case. ~3 h
2. **Spring integration fixture** — a `src/main/resources/application.yml` plus a
   `.java` file in the integration suite. ~1 h
3. **Wrapped reads** — the two-pass analysis described below. ~2 h

Roughly 6 h left. Spring is worth treating as its own phase; it costs as much as
the registry and NestJS work combined did.

## Why Spring Boot is the hard case

Java code rarely reads an environment variable directly. It reads a Spring
property, and the property file is what resolves to an environment variable:

```yaml
# application.yml
spring:
  datasource:
    url: ${DB_URL}            # the environment variable is here
```

```java
@Value("${spring.datasource.url}")   // the Java code only sees a property key
private String url;
```

So the real environment variable names live in `application.yml` /
`application.properties`, not in the Java source. Scanning `.java` alone would
find almost nothing. Three forms need covering:

- `${VAR}` in a property file — required.
- `${VAR:default}` in a property file — optional, maps to `Usage.optional=True`.
- `System.getenv("VAR")` and `System.getProperty("VAR")` in Java source — direct
  reads that bypass the property layer.

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

**Template revision comparison.** `history.py` compares the working-tree template
against its revision at the base ref, reporting added names, removed names and
changed placeholder values. Git holds the previous revision, so there is no cache.

Caching *real* values was considered and rejected: it would mean storing secrets
at rest, it would require the tool to read production configuration, and a
rotated secret is a normal event that would generate noise. The reasoning is in
the README so it does not get re-litigated.

## Open questions

- Should a Spring project compare against `.env.example` at all, or against a
  checked-in `application-example.yml`? Deployments usually inject the values as
  real environment variables, which argues for `.env.example` staying the
  template.
- Next.js splits `.env.local`, `.env.development` and `.env.production`. Worth
  auto-detecting the template per stack instead of requiring `--template`.
