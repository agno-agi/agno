"""Helpers that hide the surrealdb SDK 3.x lazy builders, so callers work on every supported SDK version."""

from typing import Any, Optional


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
    return result.execute() if hasattr(result, "execute") else result
