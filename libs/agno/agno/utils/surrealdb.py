"""Helpers that hide the surrealdb SDK 3.x lazy builders, so callers work on every supported SDK version."""

import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

_MISSING_TABLE = re.compile(r"The table '[^']*' does not exist")


def run_query(client: Any, query: str, vars: Optional[dict[str, Any]] = None) -> Any:
    """Run a query and return the first statement's result."""
    result = client.query(query) if vars is None else client.query(query, vars)
    return result.first() if hasattr(result, "first") else result


async def arun_query(client: Any, query: str, vars: Optional[dict[str, Any]] = None) -> Any:
    """Async variant of run_query."""
    result = client.query(query) if vars is None else client.query(query, vars)
    return await (result.first() if hasattr(result, "first") else result)


def run_delete(client: Any, record: Any) -> Any:
    """Delete a record or table and return the deleted rows."""
    result = client.delete(record)
    result = result.execute() if hasattr(result, "execute") else result
    return None if is_missing_table_result(result) else result


def is_missing_table_result(result: Any) -> bool:
    """Return whether a result is the missing-table error that surrealdb SDK 1.x returns instead of raising."""
    return isinstance(result, str) and _MISSING_TABLE.search(result) is not None


def is_missing_table_error(error: BaseException) -> bool:
    """Return whether the root cause of an error is a missing table."""
    while error.__cause__ is not None:
        error = error.__cause__
    return is_missing_table_result(str(error))


@contextmanager
def ignore_missing_table() -> Iterator[None]:
    """Swallow missing-table errors, so callers need no INFO FOR DB access to detect them."""
    try:
        yield
    except Exception as e:
        if not is_missing_table_error(e):
            raise
