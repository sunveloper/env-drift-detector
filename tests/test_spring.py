"""Tests for Spring Boot support.

Two extractors cover it. The property-placeholder one reads ``${VAR}`` from
``application.yml`` / ``application.properties`` - where a Spring project's
environment variable names actually live - and the Java one covers
``System.getenv`` / ``System.getProperty``, which bypass the property layer.
"""

from __future__ import annotations

from env_drift.scanner import scan_java, scan_property_placeholders


def by_name(usages):
    return {u.name: u for u in usages}


# --- property placeholders --------------------------------------------------


def test_plain_placeholder_is_required():
    yaml = "spring:\n  datasource:\n    url: ${DB_URL}\n"
    usage = by_name(scan_property_placeholders(yaml, "application.yml"))["DB_URL"]
    assert (usage.optional, usage.line) == (False, 3)


def test_placeholder_with_a_default_is_optional():
    usage = by_name(scan_property_placeholders("port: ${APP_PORT:8080}\n", "application.yml"))
    assert (usage["APP_PORT"].optional, usage["APP_PORT"].default) == (True, "8080")


def test_only_the_first_colon_separates_the_default():
    # A JDBC URL default is full of colons and slashes.
    yaml = "url: ${DB_URL:jdbc:postgresql://localhost:5432/app}\n"
    usage = by_name(scan_property_placeholders(yaml, "application.yml"))["DB_URL"]
    assert usage.default == "jdbc:postgresql://localhost:5432/app"


def test_empty_default_is_still_a_default():
    usage = by_name(scan_property_placeholders("a: ${OPTIONAL_ONE:}\n", "application.yml"))
    assert (usage["OPTIONAL_ONE"].optional, usage["OPTIONAL_ONE"].default) == (True, "")


def test_spring_property_keys_are_not_environment_variables():
    # Lower-case dotted keys resolve against a property source, not the environment.
    java = '@Value("${spring.datasource.url}")\n'
    assert scan_property_placeholders(java, "App.java") == []


def test_value_annotation_naming_an_env_var_directly_is_detected():
    java = '@Value("${DB_PASSWORD}")\nprivate String password;\n'
    assert "DB_PASSWORD" in by_name(scan_property_placeholders(java, "App.java"))


def test_properties_file_syntax_is_handled():
    text = "spring.datasource.url=${DB_URL}\nserver.port=${APP_PORT:8080}\n"
    usages = by_name(scan_property_placeholders(text, "application.properties"))
    assert usages["DB_URL"].optional is False
    assert usages["APP_PORT"].optional is True


def test_commented_lines_are_skipped():
    yaml = "# url: ${COMMENTED_YAML}\n! key=${COMMENTED_PROPS}\nreal: ${REAL_ONE}\n"
    assert list(by_name(scan_property_placeholders(yaml, "application.yml"))) == ["REAL_ONE"]


def test_trailing_comment_is_not_scanned():
    yaml = "url: ${REAL_ONE}  # or ${MENTIONED_IN_COMMENT}\n"
    assert list(by_name(scan_property_placeholders(yaml, "application.yml"))) == ["REAL_ONE"]


def test_github_actions_expressions_are_not_env_reads():
    # ${{ ... }} cannot match: a brace does not start an upper-snake-case name.
    workflow = "run: echo ${{ secrets.TOKEN }}\nif: ${{ github.event_name }}\n"
    assert scan_property_placeholders(workflow, ".github/workflows/ci.yml") == []


def test_docker_compose_dash_default_is_optional():
    # ${VAR:-default} and ${VAR-default} are the shell and compose spellings.
    compose = "environment:\n  A: ${ALPHA:-one}\n  B: ${BRAVO-two}\n"
    usages = by_name(scan_property_placeholders(compose, "compose.yaml"))
    assert (usages["ALPHA"].optional, usages["ALPHA"].default) == (True, "one")
    assert (usages["BRAVO"].optional, usages["BRAVO"].default) == (True, "two")


def test_error_if_unset_spelling_stays_required():
    # ${VAR:?message} means "fail if unset" - the message is not a fallback.
    compose = "a: ${ALPHA:?must be set}\nb: ${BRAVO?required}\n"
    usages = by_name(scan_property_placeholders(compose, "compose.yaml"))
    assert usages["ALPHA"].optional is False
    assert usages["BRAVO"].optional is False


def test_several_placeholders_on_one_line_are_all_found():
    yaml = "url: ${DB_HOST}:${DB_PORT}\n"
    assert set(by_name(scan_property_placeholders(yaml, "application.yml"))) == {
        "DB_HOST",
        "DB_PORT",
    }


def test_line_numbers_survive_a_multi_line_file():
    yaml = "one: 1\ntwo: 2\nthree: ${THIRD}\n"
    assert scan_property_placeholders(yaml, "application.yml")[0].line == 3


# --- Java / Kotlin ----------------------------------------------------------


def test_system_getenv_is_required():
    java = 'String url = System.getenv("DATABASE_URL");\n'
    assert by_name(scan_java(java, "App.java"))["DATABASE_URL"].optional is False


def test_system_getproperty_with_a_default_is_optional():
    java = 'String p = System.getProperty("APP_PORT", "8080");\n'
    usage = by_name(scan_java(java, "App.java"))["APP_PORT"]
    assert (usage.optional, usage.default) == (True, "8080")


def test_kotlin_elvis_fallback_is_optional():
    kotlin = 'val port = System.getenv("APP_PORT") ?: "8080"\n'
    usage = by_name(scan_java(kotlin, "App.kt"))["APP_PORT"]
    assert (usage.optional, usage.default) == (True, "8080")


def test_dotted_property_keys_are_ignored():
    # System.getProperty("spring.profiles.active") is a JVM namespace, not an env var.
    java = 'System.getProperty("spring.profiles.active");\n'
    assert scan_java(java, "App.java") == []


def test_computed_default_is_optional_without_a_quotable_value():
    java = 'String p = System.getProperty("APP_PORT", computeDefault());\n'
    usage = by_name(scan_java(java, "App.java"))["APP_PORT"]
    assert (usage.optional, usage.default) == (True, None)


def test_whitespace_around_the_call_is_tolerated():
    java = 'String u = System . getenv ( "DATABASE_URL" ) ;\n'
    assert "DATABASE_URL" in by_name(scan_java(java, "App.java"))


def test_line_numbers_are_recorded():
    java = "class App {\n  String u = System.getenv(\"TOKEN\");\n}\n"
    assert scan_java(java, "App.java")[0].line == 2


def test_both_java_extractors_see_one_file():
    # A Spring class reads a placeholder and calls System.getenv in the same file.
    from env_drift.extractors import default_registry

    source = (
        '@Value("${DB_URL}")\n'
        "private String url;\n"
        'private String token = System.getenv("API_TOKEN");\n'
    )
    names = {u.name for u in default_registry.extract(source, "App.java")}
    assert names == {"DB_URL", "API_TOKEN"}
