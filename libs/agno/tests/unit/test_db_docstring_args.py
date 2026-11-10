"""The database backends' docstrings must name arguments the backend accepts.

A copy-pasted adapter method carried an ``Args:`` entry for
``create_table_if_not_found`` long after the flag left the backend interface, so
anyone reading the docstring to wire a database was pointed at an argument no
signature accepts. The entry spread by copy-paste across nine adapters; this
test keeps it from coming back the same way.
"""

from __future__ import annotations

import ast
from pathlib import Path

DB_ROOT = Path(__file__).resolve().parents[2] / "agno" / "db"
STALE_ARG = "create_table_if_not_found"


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def test_db_docstrings_do_not_document_create_table_if_not_found():
    """A docstring may only list arguments its signature accepts."""
    offenders = []
    for path in sorted(DB_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _functions(tree):
            docstring = ast.get_docstring(node) or ""
            if STALE_ARG not in docstring:
                continue
            args = node.args
            accepted = {arg.arg for arg in list(args.args) + list(args.kwonlyargs)}
            if STALE_ARG not in accepted:
                offenders.append(f"{path.relative_to(DB_ROOT)}:{node.lineno} {node.name}()")

    assert not offenders, (
        "These docstrings document an argument their signature does not accept: "
        f"{offenders}"
    )
