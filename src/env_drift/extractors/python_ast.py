"""Python extractor: ``os.getenv`` and ``os.environ`` access, via the ``ast`` module.

Parsing rather than text matching is what makes a name inside a comment or a
docstring a non-issue.
"""

from __future__ import annotations

import ast

from ..models import Usage
from .base import NO_FALLBACK

SUFFIXES = frozenset({".py", ".pyi"})

# Attribute names that mean "read an environment variable" when called.
_GETTER_ATTRS = frozenset({"getenv", "get", "setdefault"})


class _EnvVisitor(ast.NodeVisitor):
    """Collect env var names from ``os.getenv`` / ``os.environ`` access."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.usages: list[Usage] = []

    # os.getenv("A") / os.environ.get("A") / environ.setdefault("A", ...)
    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _GETTER_ATTRS:
            if self._reads_environ(func) and node.args:
                self._record(node.args[0], node.lineno, self._fallback_of(node))
        self.generic_visit(node)

    # os.environ["A"] - subscripting raises KeyError when unset, so always required.
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_environ(node.value):
            self._record(node.slice, node.lineno, NO_FALLBACK)
        self.generic_visit(node)

    def _fallback_of(self, node: ast.Call) -> tuple[bool, str | None]:
        """Whether this call has a fallback, and its literal value if readable.

        ``setdefault`` writes the default into the environment, so it is optional
        by construction even though its second argument is not named "default".
        """
        if len(node.args) < 2:
            # getenv("X") and environ.get("X") both return None, which the caller
            # still has to handle - not a usable default, so the read is required.
            return NO_FALLBACK
        second = node.args[1]
        if isinstance(second, ast.Constant) and second.value is None:
            # os.getenv("X", None) is an explicit "no default".
            return NO_FALLBACK
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


def _literal_of(node: ast.expr) -> str | None:
    """Render a constant fallback for display, or None if it is computed."""
    if isinstance(node, ast.Constant):
        return "" if node.value is None else str(node.value)
    return None


class PythonExtractor:
    name = "python"
    suffixes = SUFFIXES
    filenames = frozenset()

    def extract(self, source: str, relative_path: str) -> list[Usage]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        visitor = _EnvVisitor(relative_path)
        visitor.visit(tree)
        return visitor.usages
