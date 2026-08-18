# TODO — multi-stack support

Remaining work to extend scanning beyond Python, JS/TS and NestJS. This file
records the design so the next session can pick it up without re-deriving it.

## Current coverage

| Stack | Status | Gap |
| --- | --- | --- |
| Python | Supported | — |
| Node.js | Supported | — |
| Next.js | Supported | Template is usually `.env.local`, so callers must pass `--template .env.local` |
| NestJS | Supported | — |
| Java / Spring Boot | Not supported | `.java`, `application.yml` and `application.properties` are never scanned |

## Done: extractor registry (phase 1)

`scan_file` no longer branches on suffix. `extractors/base.py` defines the
`Extractor` protocol and a `Registry` that answers "who handles this file?", and
`scanner.py` holds no language knowledge at all — it decides which files to open
and hands each to the registry.

```
src/env_drift/extractors/
  base.py           Extractor protocol, Registry, NO_FALLBACK
  python_ast.py     os.getenv / os.environ
  javascript.py     process.env / import.meta.env, plus shared fallback helpers
  nest.py           configService.get('X')
  __init__.py       DEFAULT_EXTRACTORS and default_registry
```

More than one extractor can claim a file, which is how a Nest `.ts` file is
scanned for both `process.env` and `ConfigService`. Adding a stack means adding a
module and appending it to `DEFAULT_EXTRACTORS`.

## Done: NestJS (phase 2)

`nest.py` covers `configService.get('X')`, the TS generic form `get<string>('X')`,
the second-argument default `get('X', 3000)`, a trailing `??` / `||` fallback, and
`getOrThrow` as always-required.

Two restrictions keep `ConfigService`'s non-environment uses out of the report:
the receiver name must contain "config", and the key must be upper snake case
(Nest's namespaced keys such as `app.port` resolve against a config object, not
the environment).

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
- `${VAR:default}` in a property file — optional, has a fallback.
- `System.getenv("VAR")` and `System.getProperty("VAR")` in Java source — direct
  reads that bypass the property layer.

## Design: extractor registry

Replace the suffix branch in `scan_file` with a registry of per-language
extractors, so adding a stack means adding a file rather than editing the
dispatcher (Open/Closed principle).

```python
# src/env_drift/extractors/base.py
from typing import Protocol

class Extractor(Protocol):
    name: str
    suffixes: frozenset[str]
    filenames: frozenset[str]   # for application.yml, matched by name not suffix

    def extract(self, source: str, relative_path: str) -> list[Usage]: ...
```

Target layout:

```
src/env_drift/extractors/
  base.py           Protocol, registry, and file -> extractor lookup
  python_ast.py     os.getenv / os.environ            (move existing code here)
  javascript.py     process.env / import.meta.env     (move existing code here)
  nest.py           configService.get('X')
  java.py           System.getenv / System.getProperty
  spring_props.py   ${VAR} and ${VAR:default} in yml / properties
```

After the refactor `scan_file` shrinks to: find the extractor that claims this
file, call `extract`, return the usages. `drift.py` and `reporters/` need no
changes at all — they only ever see `list[Usage]`.

## Done: optional usages

`Usage.optional` and `Usage.default` exist, and `drift.compare` reports a
variable as missing only when at least one read has no fallback. Reads with a
fallback land in `DriftReport.optional_undocumented`, which reports without
failing the build.

The new extractors inherit this for free: Spring's `${VAR:default}` and Nest's
`configService.get('X') ?? 'fallback'` map to `optional=True`, with the literal
captured in `default` when it is readable.

## Remaining plan

1. **Spring Boot extractors** — `spring_props.py` for `${VAR}` / `${VAR:default}`
   in `application.yml` and `application.properties`, plus `java.py` for
   `System.getenv` and `System.getProperty`. `filenames` on the protocol already
   exists for the `application.*` case. ~3 h
2. **Spring integration fixture** — a `src/main/resources/application.yml` plus a
   `.java` file in the integration suite. ~1 h
3. **Wrapped reads** — the two-pass analysis described below. ~2 h

Roughly 6 h left. Spring is worth treating as its own phase; it costs as much as
phases 1 and 2 combined did.

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
parameter. That is a two-pass analysis (collect wrapper signatures, then resolve
call sites), so it belongs after the extractor registry refactor rather than
bolted onto the current visitor. Estimated ~2 h once the registry exists.

Workaround until then: list the names in `ENV_DRIFT_IGNORE`.

## Open questions

- Should a Spring project compare against `.env.example` at all, or against a
  checked-in `application-example.yml`? Deployments usually inject the values as
  real environment variables, which argues for `.env.example` staying the
  template.
- Next.js splits `.env.local`, `.env.development` and `.env.production`. Worth
  auto-detecting the template per stack instead of requiring `--template`.

## Not yet verified

`pytest` has not been run against the current code. Do that before starting the
refactor, so a failure afterwards is unambiguously caused by the refactor.
