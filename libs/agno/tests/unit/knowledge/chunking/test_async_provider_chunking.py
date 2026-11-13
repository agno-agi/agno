import asyncio
import threading
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.document.base import Document
from agno.knowledge.embedder.base import Embedder
from agno.models.response import ModelResponse


def make_agentic(model):
    with patch("agno.knowledge.chunking.agentic.get_model", return_value=model):
        return AgenticChunking(model=model, max_chunk_size=8, custom_prompt="Keep sentences together")


async def test_agentic_awaits_model_and_preserves_chunks():
    entered, release = asyncio.Event(), asyncio.Event()

    async def response(*args, **kwargs):
        entered.set()
        await release.wait()
        return ModelResponse(content="4")

    model = Mock(response=Mock(return_value=ModelResponse(content="4")), aresponse=AsyncMock(side_effect=response))
    strategy = make_agentic(model)
    document = Document(id="source", name="source", content="One two three four five", meta_data={"source": "local"})
    expected = strategy.chunk(document)
    model.response.reset_mock()
    task = asyncio.create_task(strategy.achunk(document))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not task.done()
    finally:
        release.set()
        actual = await task
    assert actual == expected
    model.response.assert_not_called()
    assert model.aresponse.await_count > 0


@pytest.mark.parametrize(
    "response", [ModelResponse(content="0"), ModelResponse(content="bad"), RuntimeError("offline")]
)
async def test_agentic_async_keeps_sync_error_and_breakpoint_behavior(response):
    model = Mock()
    if isinstance(response, Exception):
        model.response.side_effect = response
        model.aresponse = AsyncMock(side_effect=response)
    else:
        model.response.return_value = response
        model.aresponse = AsyncMock(return_value=response)
    strategy = make_agentic(model)
    document = Document(content="One two three four five")
    assert await strategy.achunk(document) == strategy.chunk(document)
    assert model.aresponse.await_count > 0


async def test_agentic_async_cancellation_propagates():
    model = Mock(response=Mock(return_value=ModelResponse(content="4")))
    model.aresponse = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await make_agentic(model).achunk(Document(content="One two three four five"))


class GatedEmbedder(Embedder):
    def __init__(self, loop=None, entered=None, release=None, error=False):
        super().__init__(dimensions=4)
        self.loop, self.entered, self.release = loop, entered, release
        self.error = error

    def get_embedding(self, text):
        if self.entered is not None:
            self.loop.call_soon_threadsafe(self.entered.set)
            self.release.wait(timeout=1)
        if self.error:
            raise RuntimeError("embedding unavailable")
        return [1.0, 0.0, 0.0, 0.5]


def semantic(embedder):
    return SemanticChunking(embedder=embedder, chunk_size=30, min_characters_per_sentence=1)


def semantic_document():
    return Document(
        id="source",
        name="local",
        content="Cats enjoy the sun. Cats rest on warm rugs. Dogs enjoy a walk. Dogs visit the park.",
        meta_data={"source": "test"},
    )


async def test_semantic_embedding_allows_other_coroutines_to_progress():
    entered, release = asyncio.Event(), threading.Event()
    strategy = semantic(GatedEmbedder(asyncio.get_running_loop(), entered, release))
    document = semantic_document()
    task = asyncio.create_task(strategy.achunk(document))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert not task.done()
    finally:
        release.set()
        chunks = await task
    assert chunks == semantic(GatedEmbedder()).chunk(document)
    assert document.meta_data == {"source": "test"}


async def test_semantic_async_propagates_embedding_error():
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await semantic(GatedEmbedder(error=True)).achunk(semantic_document())


async def test_semantic_cancellation_does_not_stop_the_worker_thread():
    entered, release = asyncio.Event(), threading.Event()
    task = asyncio.create_task(
        semantic(GatedEmbedder(asyncio.get_running_loop(), entered, release)).achunk(semantic_document())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()


async def test_empty_and_small_documents_need_no_provider_calls():
    model = Mock(aresponse=AsyncMock())
    document = Document(content="short")
    assert await make_agentic(model).achunk(document) == [document]
    model.aresponse.assert_not_called()
    empty = Document(content="")
    assert await semantic(GatedEmbedder(error=True)).achunk(empty) == [empty]
