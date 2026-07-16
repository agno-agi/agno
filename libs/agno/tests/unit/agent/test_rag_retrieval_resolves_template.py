"""Knowledge retrieval must run on the resolved query, not the literal template. With
resolve_in_context=True (the default), retrieval fired before template variables were
substituted, so RAG searched for "Tell me about {topic}" instead of the resolved text."""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


class MockModel(Model):
    def __init__(self):
        super().__init__(id="m", name="m", provider="t")
        self._r = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *a, **k) -> ModelResponse:
        return self._r

    async def ainvoke(self, *a, **k) -> ModelResponse:
        return self._r

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._r

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._r
        return

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return self._r

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._r


def _agent_capturing_query(captured):
    def retriever(agent=None, query=None, **kwargs):
        captured["query"] = query
        return [{"content": "doc", "meta_data": {}}]

    return Agent(
        model=MockModel(),
        knowledge_retriever=retriever,
        add_knowledge_to_context=True,
        search_knowledge=False,
        dependencies={"topic": "quantum physics"},
        resolve_in_context=True,
    )


def test_retrieval_uses_resolved_query_sync():
    captured = {}
    _agent_capturing_query(captured).run("Tell me about {topic}")
    assert captured["query"] == "Tell me about quantum physics"


@pytest.mark.asyncio
async def test_retrieval_uses_resolved_query_async():
    captured = {}
    await _agent_capturing_query(captured).arun("Tell me about {topic}")
    assert captured["query"] == "Tell me about quantum physics"
