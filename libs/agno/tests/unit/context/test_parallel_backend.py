"""Unit tests for ``ParallelBackend`` (direct ``parallel-web`` SDK backend).

These don't hit Parallel. They mock the async client and assert that:

- ``web_search`` calls the GA top-level ``client.search`` with the new kwargs
  (``search_queries``/``objective``/``mode``) and slices results client-side.
- ``web_extract`` calls the GA top-level ``client.extract`` with the new
  ``advanced_settings={"full_content": {"max_chars_per_result": N}}`` shape.
- The JSON output shape is unchanged from the pre-1.0 backend.

The backend caches its client in ``_client``; setting it directly short-circuits
the lazy ``from parallel import AsyncParallel`` import so no SDK call is made.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agno.context.web.parallel import _MAX_EXTRACT_CHARS, ParallelBackend


def _tools(backend: ParallelBackend) -> dict:
    """Return the backend's tools keyed by name."""
    return {t.name: t for t in backend.get_tools()}


def _search_result(url: str, title: str, excerpts: list[str]):
    return SimpleNamespace(url=url, title=title, excerpts=excerpts)


# ---------------------------------------------------------------------------
# Status / config
# ---------------------------------------------------------------------------


def test_parallel_backend_missing_api_key_fails_status(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    b = ParallelBackend()
    status = b.status()
    assert status.ok is False
    assert "PARALLEL_API_KEY" in status.detail


def test_parallel_backend_exposes_search_and_extract_tools():
    b = ParallelBackend(api_key="x")
    assert sorted(_tools(b)) == ["web_extract", "web_search"]


@pytest.mark.asyncio
async def test_web_search_without_api_key_returns_error(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    b = ParallelBackend()
    out = json.loads(await _tools(b)["web_search"].entrypoint(objective="anything"))
    assert out == {"error": "PARALLEL_API_KEY not configured"}


# ---------------------------------------------------------------------------
# web_search — GA top-level client.search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_calls_ga_search_with_new_kwargs_and_shape():
    b = ParallelBackend(api_key="x")

    # 10 results back; the tool must slice to max_results client-side. The
    # first result carries >5 excerpts to confirm the [:5] cap survives.
    results = [
        _search_result(
            f"https://example.com/{i}",
            f"Title {i}",
            [f"excerpt {i}.{j}" for j in range(7)],
        )
        for i in range(10)
    ]
    fake_search = AsyncMock(return_value=SimpleNamespace(results=results))
    b._client = SimpleNamespace(search=fake_search)

    raw = await _tools(b)["web_search"].entrypoint(objective="find the thing", max_results=3)
    out = json.loads(raw)

    # New GA surface: top-level client.search with search_queries + objective + mode.
    fake_search.assert_awaited_once_with(
        search_queries=["find the thing"],
        objective="find the thing",
        mode="advanced",
    )

    # JSON shape unchanged: results: [{url, title, excerpts: [...]}, ...]
    assert list(out) == ["results"]
    assert len(out["results"]) == 3  # sliced client-side to max_results
    assert out["results"][0] == {
        "url": "https://example.com/0",
        "title": "Title 0",
        "excerpts": ["excerpt 0.0", "excerpt 0.1", "excerpt 0.2", "excerpt 0.3", "excerpt 0.4"],
    }


@pytest.mark.asyncio
async def test_web_search_handles_empty_results():
    b = ParallelBackend(api_key="x")
    b._client = SimpleNamespace(search=AsyncMock(return_value=SimpleNamespace(results=None)))
    out = json.loads(await _tools(b)["web_search"].entrypoint(objective="nothing"))
    assert out == {"results": []}


@pytest.mark.asyncio
async def test_web_search_returns_error_on_client_exception():
    b = ParallelBackend(api_key="x")
    b._client = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("boom")))
    out = json.loads(await _tools(b)["web_search"].entrypoint(objective="x"))
    assert out["error"] == "RuntimeError: boom"


# ---------------------------------------------------------------------------
# web_extract — GA top-level client.extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_extract_calls_ga_extract_with_advanced_settings_and_shape():
    b = ParallelBackend(api_key="x")

    extract_result = SimpleNamespace(results=[SimpleNamespace(full_content="full page body")])
    fake_extract = AsyncMock(return_value=extract_result)
    b._client = SimpleNamespace(extract=fake_extract)

    raw = await _tools(b)["web_extract"].entrypoint(url="https://example.com/page")
    out = json.loads(raw)

    # New GA surface: advanced_settings.full_content.max_chars_per_result, not full_content=True.
    fake_extract.assert_awaited_once_with(
        urls=["https://example.com/page"],
        advanced_settings={"full_content": {"max_chars_per_result": _MAX_EXTRACT_CHARS}},
    )

    # JSON shape unchanged: {url, content}.
    assert out == {"url": "https://example.com/page", "content": "full page body"}


@pytest.mark.asyncio
async def test_web_extract_truncates_content_to_max_chars():
    b = ParallelBackend(api_key="x")
    body = "a" * (_MAX_EXTRACT_CHARS + 1000)
    extract_result = SimpleNamespace(results=[SimpleNamespace(full_content=body)])
    b._client = SimpleNamespace(extract=AsyncMock(return_value=extract_result))

    out = json.loads(await _tools(b)["web_extract"].entrypoint(url="https://example.com"))
    assert len(out["content"]) == _MAX_EXTRACT_CHARS


@pytest.mark.asyncio
async def test_web_extract_handles_empty_results():
    b = ParallelBackend(api_key="x")
    b._client = SimpleNamespace(extract=AsyncMock(return_value=SimpleNamespace(results=[])))
    out = json.loads(await _tools(b)["web_extract"].entrypoint(url="https://example.com"))
    assert out == {"url": "https://example.com", "content": ""}


@pytest.mark.asyncio
async def test_web_extract_returns_error_on_client_exception():
    b = ParallelBackend(api_key="x")
    b._client = SimpleNamespace(extract=AsyncMock(side_effect=ValueError("nope")))
    out = json.loads(await _tools(b)["web_extract"].entrypoint(url="https://example.com"))
    assert out["error"] == "ValueError: nope"
