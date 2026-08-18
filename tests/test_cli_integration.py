"""End-to-end tests over a real temporary git repository.

These are the tests that prove the advertised behaviour: only the pushed
commit's files are scanned, and drift in those files fails the run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from env_drift.cli import main


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "commit", "--allow-empty", "-qm", "root")
    return tmp_path


def commit_file(repo: Path, name: str, content: str, message: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def run_cli(repo: Path, *extra: str) -> int:
    return main(["--repo", str(repo), "--dry-run", *extra])


def test_missing_variable_in_pushed_commit_fails(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "app.py", "import os\nos.getenv('SECRET_KEY')\n", "read new var")

    assert run_cli(repo) == 1
    assert "SECRET_KEY" in capsys.readouterr().out


def test_documented_variable_passes(repo: Path, capsys):
    commit_file(repo, ".env.example", "SECRET_KEY=placeholder\n", "add template")
    commit_file(repo, "app.py", "import os\nos.getenv('SECRET_KEY')\n", "read var")

    assert run_cli(repo) == 0
    assert "no drift" in capsys.readouterr().out


def test_only_the_pushed_commit_is_scanned(repo: Path, capsys):
    # OLD_VAR is undocumented but belongs to an earlier commit, so a push that
    # does not touch legacy.py must not report it.
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "legacy.py", "import os\nos.getenv('OLD_VAR')\n", "legacy")
    commit_file(repo, "new.py", "import os\nos.getenv('KNOWN')\n", "new work")

    assert run_cli(repo) == 0
    assert "OLD_VAR" not in capsys.readouterr().out


def test_scan_all_finds_pre_existing_drift(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "legacy.py", "import os\nos.getenv('OLD_VAR')\n", "legacy")
    commit_file(repo, "new.py", "print('hi')\n", "unrelated")

    assert main(["--repo", str(repo), "--dry-run", "--all"]) == 1
    out = capsys.readouterr().out
    assert "OLD_VAR" in out
    assert "KNOWN" in out  # documented but unused, reported only in --all mode


def test_no_fail_flag_reports_without_failing(repo: Path):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "app.py", "import os\nos.getenv('UNDOCUMENTED')\n", "drift")

    assert run_cli(repo, "--no-fail") == 0


def test_explicit_base_ref_covers_a_multi_commit_push(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    commit_file(repo, "one.py", "import os\nos.getenv('VAR_ONE')\n", "first")
    commit_file(repo, "two.py", "import os\nos.getenv('VAR_TWO')\n", "second")

    assert run_cli(repo, "--base", base) == 1
    out = capsys.readouterr().out
    assert "VAR_ONE" in out and "VAR_TWO" in out


def test_missing_template_is_a_tool_error_not_drift(repo: Path, capsys):
    commit_file(repo, "app.py", "import os\nos.getenv('X')\n", "code only")

    assert run_cli(repo) == 2
    assert "env template not found" in capsys.readouterr().err


def test_ignore_flag_suppresses_named_vars(repo: Path):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "app.py", "import os\nos.getenv('PLATFORM_VAR')\n", "drift")

    assert run_cli(repo, "--ignore", "PLATFORM_VAR") == 0


def test_first_commit_in_repo_is_scannable(tmp_path: Path, capsys):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    commit_file(tmp_path, ".env.example", "KNOWN=x\n", "initial")

    # A repo whose HEAD has no parent must not crash on HEAD^.
    assert main(["--repo", str(tmp_path), "--dry-run"]) == 0
    assert "scanned" in capsys.readouterr().out


def test_variable_with_a_default_is_reported_but_does_not_fail(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(repo, "app.py", "import os\nos.getenv('LOG_LEVEL', 'INFO')\n", "tunable")

    assert run_cli(repo) == 0
    out = capsys.readouterr().out
    assert "LOG_LEVEL" in out
    assert "does not fail the build" in out


def test_variable_without_a_default_still_fails(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(
        repo,
        "app.py",
        "import os\nos.getenv('LOG_LEVEL', 'INFO')\nos.getenv('SECRET_KEY')\n",
        "mixed",
    )

    assert run_cli(repo) == 1
    out = capsys.readouterr().out
    assert "SECRET_KEY" in out and "LOG_LEVEL" in out


def test_nestjs_config_service_reads_are_detected(repo: Path, capsys):
    # A Nest service typically never touches process.env directly.
    commit_file(repo, ".env.example", "PORT=3000\n", "add template")
    commit_file(
        repo,
        "src/app.service.ts",
        "@Injectable()\n"
        "export class AppService {\n"
        "  constructor(private config: ConfigService) {}\n"
        "  url = this.config.get<string>('DATABASE_URL');\n"
        "  port = this.config.get('PORT', 3000);\n"
        "}\n",
        "add service",
    )

    assert run_cli(repo) == 1
    out = capsys.readouterr().out
    assert "DATABASE_URL" in out
    assert "src/app.service.ts:4" in out


def test_one_typescript_file_is_scanned_by_both_extractors(repo: Path, capsys):
    commit_file(repo, ".env.example", "KNOWN=x\n", "add template")
    commit_file(
        repo,
        "src/main.ts",
        "const mode = process.env.APP_MODE;\n"
        "const url = configService.get('DATABASE_URL');\n",
        "mixed access",
    )

    assert run_cli(repo) == 1
    out = capsys.readouterr().out
    assert "APP_MODE" in out and "DATABASE_URL" in out
