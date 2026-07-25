"""Tool parsing must resolve the pydantic version once, not once per tool."""

from importlib.metadata import version as real_version
from unittest.mock import patch

import pytest
from packaging.version import Version

from agno.tools.function import Function, _get_pydantic_version


@pytest.fixture(autouse=True)
def _isolate_pydantic_version_cache():
    """Keep the mocked version from escaping this module.

    ``_wrap_callable`` skips ``validate_call`` for coroutines when the resolved
    version is below 2.10.0, so a cached mock leaking into a later test would
    silently disable argument validation for the rest of that process. CI runs
    these tests under ``pytest-split``, which can place the tests below in
    different groups, so clearing the cache only on entry is not enough.
    """
    _get_pydantic_version.cache_clear()
    try:
        yield
    finally:
        _get_pydantic_version.cache_clear()


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
    with patch("agno.tools.function.version", return_value="2.0.0") as mocked:
        for _ in range(5):
            Function.from_callable(_tool_a, strict=False)
            Function.from_callable(_tool_b, strict=False)

    # Ten callables were wrapped, but the metadata lookup happens exactly once.
    assert mocked.call_count == 1, f"expected 1 metadata lookup, got {mocked.call_count}"


def test_cached_version_matches_the_installed_version():
    assert _get_pydantic_version() == Version(real_version("pydantic"))


def test_wrapped_tools_still_validate_arguments():
    """The cache must not change validate_call behaviour."""
    fn = Function.from_callable(_tool_b, strict=False)
    assert fn.entrypoint is not None
    assert fn.entrypoint(query="hello", limit=3) == "hello"
