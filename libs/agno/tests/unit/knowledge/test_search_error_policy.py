"""Search failures can be distinguished from a successful search with no matches."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.exceptions import EmbeddingError
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.utils import log


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, EmbeddingError])
async def test_search_raises_original_error_when_enabled(vector_db, async_mode, error_type):
    error = error_type("Search backend unavailable")
    cause = ConnectionError("Connection refused")
    error.__cause__ = cause
    vector_db.search = MagicMock(side_effect=error)
    knowledge = Knowledge(vector_db=vector_db, raise_on_search_error=True)

    with pytest.raises(error_type) as caught:
        if async_mode:
            await knowledge.asearch("query")
        else:
            knowledge.search("query")

    assert caught.value is error
    assert caught.value.__cause__ is cause


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, EmbeddingError])
async def test_search_still_returns_empty_on_error_by_default(vector_db, async_mode, error_type):
    vector_db.search = MagicMock(side_effect=error_type("Search backend unavailable"))
    knowledge = Knowledge(vector_db=vector_db)

    result = await knowledge.asearch("query") if async_mode else knowledge.search("query")

    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("raise_on_search_error", [False, True])
async def test_search_validation_errors_always_raise(vector_db, async_mode, raise_on_search_error):
    error = ValueError("Unsupported user scope")
    vector_db.search = MagicMock(side_effect=error)
    knowledge = Knowledge(vector_db=vector_db, raise_on_search_error=raise_on_search_error)

    with pytest.raises(ValueError) as caught:
        if async_mode:
            await knowledge.asearch("query")
        else:
            knowledge.search("query")

    assert caught.value is error


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("configured", [False, True])
async def test_search_still_returns_empty_without_matches(vector_db, async_mode, configured):
    knowledge = Knowledge(vector_db=vector_db if configured else None, raise_on_search_error=True)

    result = await knowledge.asearch("query") if async_mode else knowledge.search("query")

    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "fallback"])
async def test_search_preserves_results_and_scope(vector_db, mode):
    documents = [Document(content="Relevant passage")]
    original_search = vector_db.search

    def search(query, limit=5, filters=None, user_id=None):
        original_search(query, limit, filters, user_id)
        return documents

    vector_db.search = search
    if mode == "fallback":
        vector_db.async_search = AsyncMock(side_effect=NotImplementedError)
    knowledge = Knowledge(
        name="manuals",
        vector_db=vector_db,
        isolate_vector_search=True,
        raise_on_search_error=True,
    )
    filters = {"category": "guide"}
    kwargs = dict(query="query", max_results=3, filters=filters, user_id="alice")

    result = knowledge.search(**kwargs) if mode == "sync" else await knowledge.asearch(**kwargs)

    assert result == documents
    assert vector_db.search_calls == [
        {"query": "query", "limit": 3, "filters": {"category": "guide", "linked_to": "manuals"}, "user_id": "alice"}
    ]
    assert filters == {"category": "guide"}


@pytest.mark.asyncio
@pytest.mark.parametrize("raise_on_search_error", [False, True])
async def test_async_fallback_obeys_error_policy(vector_db, raise_on_search_error):
    error = RuntimeError("Sync fallback unavailable")
    vector_db.async_search = AsyncMock(side_effect=NotImplementedError)
    vector_db.search = MagicMock(side_effect=error)
    knowledge = Knowledge(vector_db=vector_db, raise_on_search_error=raise_on_search_error)

    if raise_on_search_error:
        with pytest.raises(RuntimeError) as caught:
            await knowledge.asearch("query")
        assert caught.value is error
    else:
        assert await knowledge.asearch("query") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("with_filters", [False, True])
async def test_search_tool_reports_failure_without_leaking_embedding_credentials(
    vector_db, async_mode, with_filters, caplog, monkeypatch
):
    monkeypatch.setattr(log.logger, "propagate", True)
    vector_db.search = MagicMock(side_effect=EmbeddingError("Invalid api_key=example-secret", status_code=401))
    knowledge = Knowledge(vector_db=vector_db, raise_on_search_error=True)
    factory = knowledge._create_search_tool_with_filters if with_filters else knowledge._create_search_tool
    tool = factory(async_mode=async_mode)

    result = await tool.entrypoint(query="query") if async_mode else tool.entrypoint(query="query")

    assert result == "Error searching knowledge base: EmbeddingError"
    assert "example-secret" not in result
    assert "example-secret" not in caplog.text
    assert "[redacted]" in caplog.text
