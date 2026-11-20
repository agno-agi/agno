"""A database adapter docstring may only document a return value the method produces."""

import ast
from pathlib import Path
from typing import Union

DB_ROOT = Path(__file__).resolve().parents[3] / "agno" / "db"


def _returns_value(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                return True
    return False


def _is_stub(fn: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    for decorator in fn.decorator_list:
        name = decorator.attr if isinstance(decorator, ast.Attribute) else getattr(decorator, "id", None)
        if name == "abstractmethod":
            return True
    last = fn.body[-1]
    if isinstance(last, ast.Raise) and last.exc is not None:
        exc = last.exc.func if isinstance(last.exc, ast.Call) else last.exc
        return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
    return False


def test_db_docstrings_only_document_returns_that_exist():
    offenders = []
    for path in sorted(DB_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "Returns:" not in (ast.get_docstring(node) or ""):
                continue
            if _returns_value(node) or _is_stub(node):
                continue
            offenders.append(f"{path.relative_to(DB_ROOT)}:{node.lineno} {node.name}()")

    assert not offenders, f"Docstring documents a return value the function never produces: {offenders}"
