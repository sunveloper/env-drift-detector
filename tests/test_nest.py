"""Tests for the NestJS ConfigService extractor.

The two things worth pinning are the forms Nest projects actually write, and the
two restrictions that keep ConfigService's non-environment uses out of the report.
"""

from __future__ import annotations

from env_drift.scanner import scan_nest


def by_name(usages):
    return {u.name: u for u in usages}


def test_plain_get_is_detected():
    usages = by_name(scan_nest("const url = configService.get('DATABASE_URL');\n", "a.ts"))
    assert usages["DATABASE_URL"].optional is False


def test_this_prefix_and_typescript_generic_are_handled():
    source = "const url = this.configService.get<string>('DATABASE_URL');\n"
    assert "DATABASE_URL" in by_name(scan_nest(source, "a.service.ts"))


def test_second_argument_is_a_fallback():
    usage = by_name(scan_nest("const p = configService.get('PORT', 3000);\n", "a.ts"))["PORT"]
    assert (usage.optional, usage.default) == (True, "3000")


def test_nullish_fallback_after_the_call_is_a_fallback():
    usage = by_name(scan_nest("const l = config.get('LOG_LEVEL') ?? 'info';\n", "a.ts"))
    assert (usage["LOG_LEVEL"].optional, usage["LOG_LEVEL"].default) == (True, "info")


def test_get_or_throw_stays_required():
    # getOrThrow states outright that an unset value is fatal.
    usage = by_name(scan_nest("const s = this.config.getOrThrow('JWT_SECRET');\n", "a.ts"))
    assert usage["JWT_SECRET"].optional is False


def test_get_or_throw_stays_required_even_with_a_trailing_fallback():
    source = "const s = this.config.getOrThrow('JWT_SECRET') ?? 'x';\n"
    assert by_name(scan_nest(source, "a.ts"))["JWT_SECRET"].optional is False


def test_any_receiver_containing_config_is_accepted():
    source = (
        "a = configService.get('ONE');\n"
        "b = config.get('TWO');\n"
        "c = this.appConfig.get('THREE');\n"
    )
    assert set(by_name(scan_nest(source, "a.ts"))) == {"ONE", "TWO", "THREE"}


def test_non_config_receiver_is_ignored():
    # userService.get('SOMETHING') is a data lookup, not a config read.
    assert scan_nest("const u = userService.get('USER_ID');\n", "a.ts") == []


def test_namespaced_lowercase_keys_are_ignored():
    # These resolve against a Nest config object, not the environment.
    source = "a = config.get('app.port');\nb = config.get('port');\n"
    assert scan_nest(source, "a.ts") == []


def test_line_numbers_are_recorded():
    source = "const x = 1;\nconst y = configService.get('TOKEN');\n"
    assert scan_nest(source, "a.ts")[0].line == 2


def test_multiple_reads_in_one_file_are_all_found():
    source = (
        "const a = this.configService.get<string>('DATABASE_URL');\n"
        "const b = this.configService.get('PORT', 3000);\n"
        "const c = this.configService.getOrThrow('JWT_SECRET');\n"
    )
    usages = by_name(scan_nest(source, "app.service.ts"))
    assert usages["DATABASE_URL"].optional is False
    assert usages["PORT"].optional is True
    assert usages["JWT_SECRET"].optional is False
