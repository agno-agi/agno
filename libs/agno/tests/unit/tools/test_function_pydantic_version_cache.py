"""Tool parsing must resolve the pydantic version once, not once per tool."""

from importlib.metadata import version as real_version
from unittest.mock import patch

from packaging.version import Version

from agno.tools.function import Function, _get_pydantic_version


def _tool_a(query: str) -> str:
    """Tool A.

    Args:
        query: the query string.
    """
    return query


def _tool_b(query: str, limit: int = 10) -> str:
    """Tool B.

    Args:
        query: the query string.
        limit: max results.
    """
    return query


def test_pydantic_version_is_resolved_once_across_many_tools():
    _get_pydantic_version.cache_clear()
    with patch("agno.tools.function.version", return_value="2.0.0") as mocked:
        for _ in range(5):
            Function.from_callable(_tool_a, strict=False)
            Function.from_callable(_tool_b, strict=False)

    # Ten callables were wrapped, but the metadata lookup happens exactly once.
    assert mocked.call_count == 1, f"expected 1 metadata lookup, got {mocked.call_count}"


def test_cached_version_matches_the_installed_version():
    _get_pydantic_version.cache_clear()
    assert _get_pydantic_version() == Version(real_version("pydantic"))


def test_wrapped_tools_still_validate_arguments():
    """The cache must not change validate_call behaviour."""
    _get_pydantic_version.cache_clear()
    fn = Function.from_callable(_tool_b, strict=False)
    assert fn.entrypoint is not None
    assert fn.entrypoint(query="hello", limit=3) == "hello"
