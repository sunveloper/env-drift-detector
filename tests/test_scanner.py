from pathlib import Path

from env_drift.scanner import scan_javascript, scan_python


def names(usages):
    return sorted(u.name for u in usages)


def test_detects_os_getenv_and_environ_forms():
    source = """
import os
from os import environ

a = os.getenv("ALPHA")
b = os.environ["BRAVO"]
c = os.environ.get("CHARLIE", "fallback")
d = environ.get("DELTA")
e = environ.setdefault("ECHO", "x")
"""
    assert names(scan_python(source, "app.py")) == [
        "ALPHA",
        "BRAVO",
        "CHARLIE",
        "DELTA",
        "ECHO",
    ]


def test_ignores_strings_and_comments():
    source = '''
# os.getenv("COMMENTED")
doc = """os.getenv("IN_DOCSTRING")"""
real = __import__("os").getenv("REAL")
'''
    assert names(scan_python(source, "app.py")) == ["REAL"]


def test_skips_computed_keys():
    source = """
import os
prefix = "APP_"
value = os.getenv(prefix + "NAME")
literal = os.getenv("APP_MODE")
"""
    assert names(scan_python(source, "app.py")) == ["APP_MODE"]


def test_broken_file_yields_nothing_instead_of_raising():
    assert scan_python("def broken(:\n", "bad.py") == []


def test_records_line_numbers():
    source = "import os\n\nx = os.getenv('TOKEN')\n"
    usage = scan_python(source, "svc/app.py")[0]
    assert (usage.file, usage.line) == ("svc/app.py", 3)


def test_detects_javascript_env_forms():
    source = """
const a = process.env.ALPHA;
const b = process.env["BRAVO"];
const c = import.meta.env.CHARLIE;
"""
    assert names(scan_javascript(source, "app.ts")) == ["ALPHA", "BRAVO", "CHARLIE"]


def test_javascript_line_numbers():
    source = "const x = 1;\nconst y = process.env.TOKEN;\n"
    assert scan_javascript(source, "a.js")[0].line == 2


def test_scan_file_dispatches_by_suffix(tmp_path: Path):
    from env_drift.scanner import scan_file

    py = tmp_path / "a.py"
    py.write_text("import os\nos.getenv('PY_VAR')\n", encoding="utf-8")
    md = tmp_path / "readme.md"
    md.write_text("process.env.NOT_CODE", encoding="utf-8")

    assert names(scan_file(py, tmp_path)) == ["PY_VAR"]
    assert scan_file(md, tmp_path) == []


def test_iter_source_files_skips_excluded_dirs(tmp_path: Path):
    from env_drift.scanner import iter_source_files

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("", encoding="utf-8")

    found = [p.name for p in iter_source_files(tmp_path)]
    assert found == ["app.py"]
