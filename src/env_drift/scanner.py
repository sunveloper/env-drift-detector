"""Find every environment variable a source tree reads.

Python files are parsed with the standard library's ``ast`` module, so
``os.getenv("A")`` is recognised structurally rather than by text matching -
that avoids false hits inside comments and strings. JavaScript and TypeScript
have no stdlib parser available, so they fall back to a targeted regex over
``process.env`` / ``import.meta.env`` access.

Each read is also classified as required or optional. A read that supplies its
own fallback cannot break a deployment by being unset, so it is reported without
failing the build - see ``drift.compare``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable, Sequence

from .models import Usage

PYTHON_SUFFIXES = frozenset({".py", ".pyi"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})

SUPPORTED_SUFFIXES = PYTHON_SUFFIXES | JS_SUFFIXES

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "site-packages",
    }
)

# process.env.FOO | process.env["FOO"] | import.meta.env.FOO
# The trailing group captures an immediate ?? / || fallback, which marks the read
# as optional. Only a literal fallback is captured; anything else still counts as
# optional but reports no default.
_JS_PATTERN = re.compile(
    r"""(?:process|import\.meta)\.env
        (?:
            \s*\.\s*(?P<dotted>[A-Za-z_][A-Za-z0-9_]*)
          | \s*\[\s*(?P<quote>['"`])(?P<bracket>[^'"`]+)(?P=quote)\s*\]
        )
        (?P<fallback>
            \s*(?:\?\?|\|\|)\s*
            (?:
                (?P<dquote>['"`])(?P<literal>[^'"`]*)(?P=dquote)
              | (?P<number>-?\d+(?:\.\d+)?)
              | (?P<boolean>true|false)
            )?
        )?""",
    re.VERBOSE,
)

# Attribute chains that mean "read an environment variable" when called.
_PY_GETTER_ATTRS = frozenset({"getenv", "get", "setdefault"})


class _PythonEnvVisitor(ast.NodeVisitor):
    """Collect env var names from ``os.getenv`` / ``os.environ`` access."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.usages: list[Usage] = []

    # os.getenv("A") / os.environ.get("A") / environ.setdefault("A", ...)
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _PY_GETTER_ATTRS:
            if self._reads_environ(func) and node.args:
                fallback = self._fallback_of(node, func.attr)
                self._record(node.args[0], node.lineno, fallback)
        self.generic_visit(node)

    # os.environ["A"] - subscripting raises KeyError when unset, so always required.
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environ(node.value):
            self._record(node.slice, node.lineno, _NO_FALLBACK)
        self.generic_visit(node)

    def _fallback_of(self, node: ast.Call, attr: str) -> tuple[bool, str | None]:
        """Whether this call has a fallback, and its literal value if readable.

        ``setdefault`` writes the default into the environment, so it is optional
        by construction even though the second argument is not named "default".
        """
        if len(node.args) < 2:
            # getenv("X") returns None, environ.get("X") returns None, and neither
            # is a usable default - the caller has to handle it, so treat the read
            # as required.
            return _NO_FALLBACK
        second = node.args[1]
        if isinstance(second, ast.Constant) and second.value is None:
            # os.getenv("X", None) is an explicit "no default".
            return _NO_FALLBACK
        return True, _literal_of(second)

    def _reads_environ(self, func: ast.Attribute) -> bool:
        """True for ``os.getenv`` (module-level) or ``<environ>.get`` style calls."""
        if func.attr == "getenv":
            return self._is_os_module(func.value) or isinstance(func.value, ast.Name)
        return self._is_environ(func.value)

    @staticmethod
    def _is_os_module(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "os"

    def _is_environ(self, node: ast.expr) -> bool:
        # os.environ  /  environ  /  os.environb
        if isinstance(node, ast.Attribute):
            return node.attr in {"environ", "environb"}
        return isinstance(node, ast.Name) and node.id in {"environ", "environb"}

    def _record(
        self, node: ast.expr, lineno: int, fallback: tuple[bool, str | None]
    ) -> None:
        """Only literal names are recorded - a computed key cannot be verified."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value.strip()
            if name:
                optional, default = fallback
                self.usages.append(
                    Usage(
                        name=name,
                        file=self.relative_path,
                        line=lineno,
                        optional=optional,
                        default=default,
                    )
                )


_NO_FALLBACK: tuple[bool, str | None] = (False, None)


def _literal_of(node: ast.expr) -> str | None:
    """Render a constant fallback for display, or None if it is computed."""
    if isinstance(node, ast.Constant):
        return "" if node.value is None else str(node.value)
    return None


def scan_python(source: str, relative_path: str) -> list[Usage]:
    """Return env var usages in a Python source string.

    A file that does not parse is skipped rather than raising: the tool runs in
    CI against whatever was pushed, and one syntactically broken file should not
    hide the drift in every other file.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _PythonEnvVisitor(relative_path)
    visitor.visit(tree)
    return visitor.usages


def scan_javascript(source: str, relative_path: str) -> list[Usage]:
    """Return env var usages in a JS/TS source string."""
    usages: list[Usage] = []
    for match in _JS_PATTERN.finditer(source):
        name = (match.group("dotted") or match.group("bracket") or "").strip()
        if not name:
            continue
        line = source.count("\n", 0, match.start()) + 1
        optional = match.group("fallback") is not None
        default = None
        if optional:
            literal = match.group("literal")
            default = (
                literal
                if literal is not None
                else match.group("number") or match.group("boolean")
            )
        usages.append(
            Usage(
                name=name,
                file=relative_path,
                line=line,
                optional=optional,
                default=default,
            )
        )
    return usages


def scan_file(path: Path, root: Path) -> list[Usage]:
    """Scan one file, dispatching on its suffix. Unreadable files yield nothing."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    relative_path = _relative(path, root)
    if suffix in PYTHON_SUFFIXES:
        return scan_python(source, relative_path)
    return scan_javascript(source, relative_path)


def scan_paths(paths: Iterable[Path], root: Path) -> list[Usage]:
    """Scan an explicit list of files - the git-diff driven entry point."""
    usages: list[Usage] = []
    for path in paths:
        if path.is_file():
            usages.extend(scan_file(path, root))
    return usages


def iter_source_files(
    root: Path, excluded_dirs: Sequence[str] | None = None
) -> list[Path]:
    """Walk the tree for scannable files - the ``--all`` entry point."""
    excluded = set(excluded_dirs) if excluded_dirs is not None else set(DEFAULT_EXCLUDED_DIRS)
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if excluded.intersection(path.relative_to(root).parts[:-1]):
            continue
        found.append(path)
    return found


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
